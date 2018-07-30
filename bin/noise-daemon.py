#!/usr/bin/python

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject, GLib

import os
import sys
import thread
import datetime
import time
from xvfbwrapper import Xvfb
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from urlparse import urlparse
import subprocess
import syslog
import threading

# TODO:
# - Read configuration from a file

LISTEN_PORT=5678

DETECT_LEVEL=-30
# The amount of silence before an event is considered over
EVENT_END_SILENCE=5

TARGET_DIR = "/var/lib/motion"

# Kill any virtual frame buffer that has been left running
os.system("pkill -u pi 'Xvfb'")
# Start a virtual frame buffer
vdisplay = Xvfb()
vdisplay.start()
syslog.syslog("Started Xvfb on display " + os.environ['DISPLAY'])

class NoiseDetector:
    def __init__(self):
        self.target_dir = TARGET_DIR
        self.streamer = Gst.parse_launch("autoaudiosrc ! level ! audioconvert ! audioresample ! opusenc ! tee name=tee ! queue leaky=1 ! rtpopuspay ! queue max-size-bytes=0 max-size-buffers=0 ! udpsink host={} port={}".format("127.0.0.1", "5002"))
        self.streamer.get_by_name("tee").connect("pad-added", self.tee_pad_added)
        self.bus = self.streamer.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect('message', self.on_message)
        self.recording = False
        self.event_time = None
        self.shutdown = False

    def on_message(self, bus, message):
        if message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            syslog.syslog("Error: {} {}".format(err, debug))
        if message.type == Gst.MessageType.ELEMENT:
            struct = message.get_structure()
            if struct.get_name() == 'level':
                level = struct.get_value('rms')[0]
                #syslog.syslog("SOUND " + str(level))
                if level > DETECT_LEVEL:
                    if self.event_time == None:
                        syslog.syslog("Noise detected - event started - " + str(level))
                        os.system("curl -s http://localhost:8080/0/config/set?emulate_motion=on > /dev/null")
                    self.event_time = datetime.datetime.utcnow()
                    #syslog.syslog("SOUND " + str(level))
                    #time.sleep(1)
                elif self.event_time != None:
                    # See if the event is over
                    if self.event_time + datetime.timedelta(seconds=EVENT_END_SILENCE) < datetime.datetime.utcnow():
                        self.event_time = None
                        syslog.syslog("Noise event finished")
                        os.system("curl -s http://localhost:8080/0/config/set?emulate_motion=off > /dev/null")

    def start(self):
        self.streamer.set_state(Gst.State.PLAYING)
        syslog.syslog("Noise detection enabled")
        while not self.shutdown:
            time.sleep(1)
        self.streamer.set_state(Gst.State.READY)
        syslog.syslog("Noise detection disabled")
        #time.sleep(1)
        #loop.quit()

    def is_recording(self):
        return self.recording

    def start_recording(self, rec_id):
        syslog.syslog("Started audio recording - " + rec_id)
        self.recording = True
        self.rec_id = rec_id
        # Add src pad to the tee
        tee = self.streamer.get_by_name("tee")
        self.tee_src = tee.get_request_pad("src_%u")

    def stop_recording(self):
        # Stop the recorder
        self.recorder.set_state(Gst.State.NULL)
        self.tee_src.unlink(self.recorder.get_static_pad("sink"))
        # Release the pad
        self.streamer.get_by_name("tee").release_request_pad(self.tee_src)
        self.streamer.remove(self.recorder)
        self.recorder = None
        # Combine the streams
        syslog.syslog("Stopped recording audio")
        new_name = self.rec_id
        if new_name.startswith('.'):
            new_name = new_name[1:]
        if not os.path.isfile(self.target_dir + "/" + self.rec_id + ".ogg"):
            syslog.syslog("WARNING - Audio file missing: " + self.target_dir + "/" + self.rec_id + ".ogg")
            os.rename('{}/{}.mkv'.format(self.target_dir, self.rec_id), '{}/{}.mkv'.format(self.target_dir, new_name))
            os.remove('{}/{}.log'.format(self.target_dir, self.rec_id))
        elif os.path.getsize(self.target_dir + "/" + self.rec_id + ".ogg") == 0:
            syslog.syslog("WARNING - Audio file has 0 bytes: " + self.target_dir + "/" + self.rec_id + ".ogg")
            os.rename('{}/{}.mkv'.format(self.target_dir, self.rec_id), '{}/{}.mkv'.format(self.target_dir, new_name))
            os.remove('{}/{}.ogg'.format(self.target_dir, self.rec_id))
            os.remove('{}/{}.log'.format(self.target_dir, self.rec_id))
        else:
            try:
            # Combine the video and audio
                subprocess.check_call("ffmpeg -hide_banner -loglevel quiet -i " + self.target_dir + "/" + self.rec_id + ".mkv -itsoffset 0.5 -i " + self.target_dir + "/" + self.rec_id + ".ogg -c copy -shortest " + self.target_dir + "/" + self.rec_id + "_joined.mkv", shell=True)
                # Delete the unwanted files
                os.remove('{}/{}.mkv'.format(self.target_dir, self.rec_id))
                os.remove('{}/{}.ogg'.format(self.target_dir, self.rec_id))
                os.remove('{}/{}.log'.format(self.target_dir, self.rec_id))
                os.rename('{}/{}_joined.mkv'.format(self.target_dir, self.rec_id), '{}/{}.mkv'.format(self.target_dir, new_name))
            except:
                syslog.syslog("Failed to combine audio and video files")
        self.recording = False

    def tee_pad_added(self, tee, pad):
        print("Created tee pad: " + pad.get_name())
        if not pad.get_name() == "src_0":
            filename = self.target_dir + "/" + self.rec_id + ".ogg"
            self.recorder = Gst.parse_bin_from_description("queue leaky=1 name=record_queue ! audio/x-opus ! oggmux ! filesink location={}".format(filename), True)
            self.streamer.add(self.recorder)

            pad_link_return = pad.link(self.recorder.get_static_pad("sink"))
            if pad_link_return != Gst.PadLinkReturn.OK:
                syslog.syslog("Invalid return from pad link: " + str(pad_link_return))

            self.recorder.set_state(Gst.State.PLAYING)


class NoiseHandler(BaseHTTPRequestHandler):
    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_GET(self):
        global noiseDetector
        global httpd
        global loop
        syslog.syslog("Controller received a request - " + self.path)
        query = urlparse(self.path).query
        query_components = dict(qc.split("=") for qc in query.split("&"))
        message = "Invalid request"
        if 'start_rec' in query_components and query_components['start_rec'] == 'true':
            if noiseDetector.is_recording():
                message = "Recording already in progress"
            else:
                rec_id = query_components['rec_id']
                message = "Started recording"
                thread.start_new_thread(noiseDetector.start_recording, (rec_id,))
        if 'stop_rec' in query_components and query_components['stop_rec'] == 'true':
            if noiseDetector.is_recording():
                message = "Stopped recording"
                noiseDetector.stop_recording()
            else:
                message = "Recording not in progress"
        if 'shutdown' in query_components and query_components['shutdown'] == 'true':
            if noiseDetector.is_recording():
                message = "Stopped recording"
                noiseDetector.stop_recording()
            # TODO: Shutdown gracefully
            noiseDetector.shutdown = True
            thr = threading.Thread(target=stop_listener)
            thr.start()
            #httpd.shutdown()
            message = "Shutting down"
            loop.quit()
        self._set_headers()
        self.wfile.write("<html><body><h1>" + message + "</h1></body></html>")


def start_listener():
    global LISTEN_PORT
    global httpd
    httpd = HTTPServer(('127.0.0.1', LISTEN_PORT), NoiseHandler)
    syslog.syslog("Starting http listener")
    try:
        thread.start_new_thread(httpd.serve_forever(), ())
    except:
        pass

def stop_listener():
    global httpd
    httpd.shutdown()


Gst.init(None)
# Make sure the pulse audio daemon is running
os.system("/usr/bin/pulseaudio --start --log-target=syslog")
# TODO: See if there is something that it can wait for
time.sleep(8)
# Start the detector thread
GObject.threads_init()
noiseDetector = NoiseDetector()
thread.start_new_thread(noiseDetector.start, ())
# Start the controller
httpd = None
t = threading.Thread(target=start_listener)
t.start()
loop = GLib.MainLoop()
loop.run()
sys.exit(0)
