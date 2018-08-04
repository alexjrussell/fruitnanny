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

VIDEO_SYNC_OFFSET = "2"
VIDEO_TIMESTAMP = True
VIDEO_TIMESTAMP_FONT = "/usr/share/fonts/truetype/noto/NotoMono-Regular.ttf"

DEBUG = False


class AudioStreamer:
    def __init__(self, controller):
        self.controller = controller
        self.playing = False
        self.recording = False
        self.shutdown = False
        self.target_dir = TARGET_DIR
        self.streamer = Gst.parse_launch("autoaudiosrc ! level ! audioconvert ! audioresample ! opusenc ! tee name=tee ! queue leaky=1 ! rtpopuspay ! queue max-size-bytes=0 max-size-buffers=0 ! udpsink host={} port={}".format("127.0.0.1", "5002"))
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
        self.streamer = Gst.parse_launch("rpicamsrc name=src preview=0 exposure-mode=night fullscreen=0 bitrate=1000000 ! video/x-h264,width=960,height=544,framerate=12/1 ! queue max-size-bytes=0 max-size-buffers=0 ! h264parse ! tee name=tee ! queue leaky=1 ! rtph264pay config-interval=1 pt=96 ! udpsink host=127.0.0.1 port=5004 sync=false tee. ! queue leaky=1 ! flvmux streamable=true ! rtmpsink location=rtmp://127.0.0.1:1935/cam sync=false")
        #self.streamer = Gst.parse_launch("autovideosrc ! videoconvert ! x264enc ! tee name=rectee ! queue max-size-bytes=0 max-size-buffers=0 ! h264parse ! tee name=rtmpstream ! queue leaky=1 ! rtph264pay config-interval=1 pt=96 ! udpsink host=127.0.0.1 port=5004 sync=false")
        self.streamer.get_by_name("tee").connect("pad-added", self.tee_pad_added)
        self.bus = self.streamer.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect('message', self.on_message)

    def on_message(self, bus, message):
        if message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            syslog.syslog("Error: {} {}".format(err, debug))
            self.controller.exit(-1)

    def start(self):
        self.streamer.set_state(Gst.State.PLAYING)
        self.playing = True
        syslog.syslog("Video stream started")

    def stop(self):
        self.streamer.set_state(Gst.State.READY)
        syslog.syslog("Video stream stopped")

    def is_playing(self):
        return self.playing

    def is_recording(self):
        return self.recording

    def start_recording(self, rec_id):
        syslog.syslog("Started video recording - " + rec_id)
        self.recording = True
        self.rec_id = rec_id
        # Add src pad to the tee
        tee = self.streamer.get_by_name("tee")
        self.tee_src = tee.get_request_pad("src_%u")

    def tee_pad_added(self, tee, pad):
        if not pad.get_name() == "src_0":
            filename = "{}/.{}.mkv".format(self.target_dir, self.rec_id)
            self.recorder = Gst.parse_bin_from_description("queue leaky=1 name=record_queue ! video/x-h264 ! matroskamux ! filesink location={}".format(filename), True)
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
        syslog.syslog("Stopped recording video")


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

    def set_mainloop(self, mainloop):
        self.mainloop = mainloop

    def on_signal(self, *args, **kwargs):
        if not self.videoStreamer.is_playing() or not self.audioStreamer.is_playing():
            # Ignore events if the streams are not playing yet
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
        video_file = "{}/.{}.mkv".format(self.target_dir, self.rec_id)
        if not os.path.isfile(audio_file):
            syslog.syslog("WARNING - Audio file missing: " + audio_file)
            os.rename(video_file, '{}/{}.mkv'.format(self.target_dir, self.rec_id))
        elif os.path.getsize(audio_file) == 0:
            syslog.syslog("WARNING - Audio file has 0 bytes: " + audio_file)
            os.rename(video_file, '{}/{}.mkv'.format(self.target_dir, self.rec_id))
            os.remove(audio_file)
        else:
            try:
                # Combine the video and audio
                subprocess.check_call("ffmpeg -hide_banner -loglevel quiet -i {} -itsoffset {} -i {} -c copy -shortest {}/.{}_joined.mkv".format(video_file, VIDEO_SYNC_OFFSET, audio_file, self.target_dir, self.rec_id), shell=True)
                # Delete the unwanted files
                os.remove(video_file)
                os.remove(audio_file)
                os.rename('{}/.{}_joined.mkv'.format(self.target_dir, self.rec_id), '{}/{}.mkv'.format(self.target_dir, self.rec_id))
                if VIDEO_TIMESTAMP:
                    # Calculate the time offset of the video start
                    offset_seconds = str(int(self.timestamp_offset))
                    # Add timestamp to the video
                    subprocess.check_call("ffmpeg -hide_banner -loglevel quiet -i {}/{}.mkv -vf \"drawtext=fontfile={}: text='%{{pts\\:localtime\\:{}}}': fontcolor=white@0.8: x=10: y=10\" -c:a copy -crf 26 {}/.{}_timestamped.mkv".format(self.target_dir, self.rec_id, VIDEO_TIMESTAMP_FONT, offset_seconds, self.target_dir, self.rec_id), shell=True)
                    os.remove('{}/{}.mkv'.format(self.target_dir, self.rec_id))
                    os.rename('{}/.{}_timestamped.mkv'.format(self.target_dir, self.rec_id), '{}/{}.mkv'.format(self.target_dir, self.rec_id))
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
