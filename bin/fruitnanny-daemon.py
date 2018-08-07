#!/usr/bin/python

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject, GLib

import os
import sys
import getpass
import thread
import datetime
import time
from xvfbwrapper import Xvfb
import subprocess
import syslog
import threading
import numpy
import socket
import picamera
import picamera.array

# TODO:
# - Add recording start notifications
# - Read configuration from a file
# - Make it shutdown gracefully
# - Combine the video & audio in a thread that is CPU limited
# - Restart the streamers if they fail
#   - If they repeatedly fail - 5 times in a minute, kill the whole thing


DETECT_LEVEL = -30
# The amount of silence before an event is considered over
EVENT_END_INACTIVITY = 20

# The maximum recording length in minutes
MAXIMUM_RECORDING_LENGTH = 20

TARGET_DIR = "/var/lib/motion"

VIDEO_WIDTH = 960
VIDEO_HEIGHT = 544
VIDEO_FPS = 12
VIDEO_SYNC_OFFSET = "2"

DEBUG = False


class AudioStreamer:
    def __init__(self, controller):
        self.controller = controller
        self.playing = False
        self.recording = False
        self.shutdown = False
        self.target_dir = TARGET_DIR
        self.streamer = Gst.parse_launch("alsasrc device=hw:1 ! level ! audioconvert ! audioresample ! opusenc ! tee name=tee ! queue leaky=1 ! rtpopuspay ! queue max-size-bytes=0 max-size-buffers=0 ! udpsink host={} port={}".format("127.0.0.1", "5002"))
        self.streamer.get_by_name("tee").connect("pad-added", self.tee_pad_added)
        self.bus = self.streamer.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect('message', self.on_message)

    def on_message(self, bus, message):
        if message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            syslog.syslog("Error: {} {}".format(err, debug))
            self.controller.exit(-1)
        if message.type == Gst.MessageType.ELEMENT:
            struct = message.get_structure()
            if struct.get_name() == 'level':
                level = struct.get_value('rms')[0]
                if DEBUG:
                    syslog.syslog("LEVEL = " + str(level))
                if level > DETECT_LEVEL:
                    syslog.syslog("Got event: NoiseDetected")
                    self.controller.start_recording()

    def start(self):
        self.streamer.set_state(Gst.State.PLAYING)
        self.playing = True
        syslog.syslog("Audio stream started")

    def stop(self):
        self.streamer.set_state(Gst.State.READY)
        syslog.syslog("Audio stream stopped")

    def is_playing(self):
        return self.playing

    def is_recording(self):
        return self.recording

    def start_recording(self, rec_id):
        syslog.syslog("Started audio recording - " + rec_id)
        self.recording = True
        self.rec_id = rec_id
        # Add src pad to the tee
        tee = self.streamer.get_by_name("tee")
        self.tee_src = tee.get_request_pad("src_%u")

    def tee_pad_added(self, tee, pad):
        if not pad.get_name() == "src_0":
            filename = "{}/.{}.ogg".format(self.target_dir, self.rec_id)
            self.recorder = Gst.parse_bin_from_description("queue leaky=1 name=record_queue ! audio/x-opus ! oggmux ! filesink location={}".format(filename), True)
            self.streamer.add(self.recorder)
            pad_link_return = pad.link(self.recorder.get_static_pad("sink"))
            if pad_link_return != Gst.PadLinkReturn.OK:
                syslog.syslog("Invalid return from pad link: " + str(pad_link_return))
            self.recorder.set_state(Gst.State.PLAYING)

    def stop_recording(self):
        # Stop the recorder
        self.recorder.set_state(Gst.State.NULL)
        self.tee_src.unlink(self.recorder.get_static_pad("sink"))
        # Release the pad
        self.streamer.get_by_name("tee").release_request_pad(self.tee_src)
        self.streamer.remove(self.recorder)
        self.recorder = None
        self.recording = False
        syslog.syslog("Stopped recording audio")


class VideoStreamer:

    def __init__(self, controller):
        self.controller = controller
        self.playing = False
        self.recording = False
        self.shutdown = False
        self.target_dir = TARGET_DIR
        self.camera = None
        self.connection = None
        self.resolution = (VIDEO_WIDTH, VIDEO_HEIGHT)
        self.framerate = VIDEO_FPS
        # Create the pipeline that puts h264 into rtp
        self.streamer = Gst.parse_launch("udpsrc address=127.0.0.1 port=5003 ! video/x-h264 ! h264parse ! queue ! rtph264pay config-interval=1 pt=96 ! udpsink port=5004")
        self.bus = self.streamer.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect('message', self.on_message)

    def on_message(self, bus, message):
        if message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            syslog.syslog("Error: {} {}".format(err, debug))
            self.controller.exit(-1)

    def start(self):
        # Start the gstreamer pipeline
        self.streamer.set_state(Gst.State.PLAYING)
        # Connect to the udp socket of the pipeline
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        connect_attempts = 0
        while connect_attempts != -1:
            try:
                self.client_socket.connect(('127.0.0.1', 5003))
                connect_attempts = -1
            except Exception as ex:
                time.sleep(1)
                connect_attempts += 1
                if connect_attempts >= 30:
                    syslog.syslog("Timeout connecting to gstreamer pipeline")
                    self.controller.exit(-1)
                    return
        # Open a file that connects to the udp socket
        self.connection = self.client_socket.makefile('wb')
        # Start the streaming in a thread
        stream_thread = threading.Thread(target=self.stream)
        stream_thread.daemon = True
        stream_thread.start()

    def stream(self):
        self.playing = True
        syslog.syslog("Video stream started")
        with picamera.PiCamera(resolution=self.resolution, framerate=self.framerate) as self.camera:
            self.camera.start_preview()
            # TODO: Other camera settings go here
            #self.camera.annotate_background = True
            #self.camera.annotate_text = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            syslog.syslog('Waiting 2 seconds for the camera to warm up')
            time.sleep(2)
            try:
                syslog.syslog('Started streaming')
                self.camera.start_recording(
                    self.connection, format='h264', splitter_port=1,
                    motion_output=MotionDetector(self.camera, self.controller)
                )
                self.camera.wait_recording(timeout=1, splitter_port=1)
                while not self.shutdown:
                    time.sleep(1)
            except Exception as ex:
                syslog.syslog("ERROR: " + str(ex))
            finally:
                self.camera.stop_recording(splitter_port=1)
                self.camera.stop_preview()
                syslog.syslog('Stopped streaming')
                # Close the socket
                self.connection.close()
                self.client_socket.close()
                # Stop the gstreamer pipeline
                self.streamer.set_state(Gst.State.READY)

    def stop(self):
        self.shutdown = True
        syslog.syslog("Video stream stopped")

    def is_playing(self):
        return self.playing

    def is_recording(self):
        return self.recording

    def start_recording(self, rec_id):
        syslog.syslog("Started video recording - " + rec_id)
        self.recording = True
        self.rec_id = rec_id
        filename = "{}/.{}.h264".format(self.target_dir, self.rec_id)
        self.camera.start_recording(
            filename, format='h264', splitter_port=2
        )
        self.camera.wait_recording(timeout=1, splitter_port=2)

    def stop_recording(self):
        syslog.syslog("Stopped recording video")
        self.camera.stop_recording(splitter_port=2)
        self.recording = False


class MotionDetector(picamera.array.PiMotionAnalysis):
    def __init__(self, camera, controller):
        super(MotionDetector, self).__init__(camera)
        self.controller = controller
        self.first = True

    def analyse(self, a):
        a = numpy.sqrt(
            numpy.square(a['x'].astype(numpy.float)) +
            numpy.square(a['y'].astype(numpy.float))
        ).clip(0, 255).astype(numpy.uint8)
        # If there are 50 vectors detected with a magnitude of 60.
        # We consider movement to be detected.
        if (a > 60).sum() > 50:
            # Ignore the first detection, the camera sometimes
            # triggers a false positive due to camera warmup.
            if self.first:
                self.first = False
                syslog.syslog("Ignoring first detection")
                return
            syslog.syslog("Got event: MotionDetected")
            self.controller.start_recording()


class FruitnannyController:

    def __init__(self):
        self.mainloop = None
        self.exitcode = 0
        # Start the dbus listener
        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.bus_name = dbus.service.BusName('org.freedesktop.fruitnanny', bus=self.bus)
        self.bus.add_signal_receiver(self.on_signal, dbus_interface='org.freedesktop.fruitnanny', member_keyword='event')
        # Start the streams
        self.recording = False
        self.rec_id = None
        self.rec_started = None
        self.rec_stopped = None
        self.target_dir = TARGET_DIR
        # Start the thread that checks for the end of recordings
        thread.start_new_thread(self.check_for_end, ())
        # Start the audio & video streams
        self.videoStreamer = VideoStreamer(self)
        self.audioStreamer = AudioStreamer(self)
        self.videoStreamer.start()
        self.audioStreamer.start()
        self.initializing = True
        self.init_start = datetime.datetime.utcnow()

    def set_mainloop(self, mainloop):
        self.mainloop = mainloop

    def on_signal(self, *args, **kwargs):
        if self.initializing:
            if self.init_start + datetime.timedelta(seconds=30) < datetime.datetime.utcnow():
                self.initializing = False
            else:
                return
        syslog.syslog("Got event: {}".format(kwargs['event']))
        if kwargs['event'] == "MotionDetected":
            self.start_recording()

    def start_recording(self):
        if self.recording:
            self.last_trigger = datetime.datetime.utcnow()
        else:
            self.recording = True
            self.rec_id = datetime.datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
            self.rec_started = datetime.datetime.utcnow()
            self.timestamp_offset = time.time()
            self.last_trigger = self.rec_started
            self.videoStreamer.start_recording(self.rec_id)
            self.audioStreamer.start_recording(self.rec_id)

    def check_for_end(self):
        while True:
            if self.recording:
                if self.last_trigger + datetime.timedelta(seconds=EVENT_END_INACTIVITY) < datetime.datetime.utcnow():
                    # The inactivity period has finished
                    self.stop_recording()
                elif self.rec_started + datetime.timedelta(minutes=MAXIMUM_RECORDING_LENGTH) < datetime.datetime.utcnow():
                    # The maximum recording length has been reached
                    self.stop_recording()
            time.sleep(1)

    def stop_recording(self):
        self.videoStreamer.stop_recording()
        self.audioStreamer.stop_recording()
        self.rec_stopped = datetime.datetime.utcnow()
        duration = int((self.rec_stopped - self.rec_started).total_seconds())
        syslog.syslog("Recording duration = {} seconds".format(str(duration)))
        # Combine the streams
        audio_file = "{}/.{}.ogg".format(self.target_dir, self.rec_id)
        video_file = "{}/.{}.h264".format(self.target_dir, self.rec_id)
        if not os.path.isfile(audio_file):
            syslog.syslog("WARNING - Audio file missing: " + audio_file)
            subprocess.check_call("ffmpeg -hide_banner -loglevel quiet -i {} -c copy {}/{}.mkv".format(video_file, self.target_dir, self.rec_id), shell=True)
            os.remove(video_file)
        elif os.path.getsize(audio_file) == 0:
            syslog.syslog("WARNING - Audio file has 0 bytes: " + audio_file)
            subprocess.check_call("ffmpeg -hide_banner -loglevel quiet -i {} -c copy {}/{}.mkv".format(video_file, self.target_dir, self.rec_id), shell=True)
            os.remove(video_file)
        else:
            try:
                # Combine the video and audio
                subprocess.check_call("ffmpeg -hide_banner -loglevel quiet -i {} -itsoffset {} -i {} -c copy -shortest {}/.{}_joined.mkv".format(video_file, VIDEO_SYNC_OFFSET, audio_file, self.target_dir, self.rec_id), shell=True)
                # Delete the unwanted files
                os.remove(video_file)
                os.remove(audio_file)
                os.rename('{}/.{}_joined.mkv'.format(self.target_dir, self.rec_id), '{}/{}.mkv'.format(self.target_dir, self.rec_id))
                syslog.syslog("New recording file {}/{}.mkv".format(self.target_dir, self.rec_id))
            except Exception,e:
                syslog.syslog("Failed to combine audio and video files - " + str(e))
        self.recording = False

    def exit(self, exitcode):
        self.exitcode = exitcode
        self.mainloop.quit()

    def get_exitcode(self):
        return self.exitcode


# Kill any virtual frame buffer that has been left running
os.system("pkill -u {} 'Xvfb'".format(getpass.getuser()))
# Start a virtual frame buffer
vdisplay = Xvfb()
vdisplay.start()
syslog.syslog("Started Xvfb on display " + os.environ['DISPLAY'])

Gst.init(None)
# Make sure the pulse audio daemon is running
os.system("/usr/bin/pulseaudio --start --log-target=syslog")
# TODO: See if there is something that it can wait for
time.sleep(8)
# Start the detector thread
GObject.threads_init()
# Start the controller
controller = FruitnannyController()
# Start the main loop
loop = GLib.MainLoop()
controller.set_mainloop(loop)
loop.run()
sys.exit(controller.get_exitcode())
