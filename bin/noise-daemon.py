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

DETECT_LEVEL=-15
#DETECT_LEVEL=-30
# The amount of silence before an event is considered over
EVENT_END_SILENCE=5

recorder = None

# Kill any virtual frame buffer that has been left running
os.system("pkill -u pi 'Xvfb'")
# Start a virtual frame buffer
vdisplay = Xvfb()
vdisplay.start()
syslog.syslog("Started Xvfb on display " + os.environ['DISPLAY'])

class NoiseDetector:
    def __init__(self):
        test = """
        alsasrc device=plug:dsnooper ! level ! audioconvert ! audioresample ! opusenc ! rtpopuspay ! queue max-size-bytes=0 max-size-buffers=0 ! udpsink host=127.0.0.1 port=5002
        """
        self.pipeline = Gst.parse_launch(test)
        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect('message', self.playerbinMessage)
        self.event_time = None
        self.shutdown = False

    def playerbinMessage(self, bus, message):
        if message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            syslog.syslog("Error: {} {}".format(err, debug))
        if message.type == Gst.MessageType.ELEMENT:
            struct = message.get_structure()
            if struct.get_name() == 'level':
                #print "SOUND " + str(struct['peak'][0]), str(struct['decay'][0]), str(struct['rms'][0])
                #syslog.syslog("SOUND " + str(struct['rms'][0]))
                if struct['rms'][0] > DETECT_LEVEL:
                    if self.event_time == None:
                        syslog.syslog("Noise detected - event started - " + str(struct['rms'][0]))
                        os.system("curl -s http://localhost:8080/0/config/set?emulate_motion=on > /dev/null")
                    self.event_time = datetime.datetime.utcnow()
                    #syslog.syslog("SOUND " + str(struct['rms'][0]))
                    #time.sleep(1)
                elif self.event_time != None:
                    # See if the event is over
                    if self.event_time + datetime.timedelta(seconds=EVENT_END_SILENCE) < datetime.datetime.utcnow():
                        self.event_time = None
                        syslog.syslog("Noise event finished")
                        os.system("curl -s http://localhost:8080/0/config/set?emulate_motion=off > /dev/null")

    def start(self):
        self.pipeline.set_state(Gst.State.PLAYING)
        syslog.syslog("Noise detection enabled")
        while not self.shutdown:
            time.sleep(1)
        self.pipeline.set_state(Gst.State.READY)
        syslog.syslog("Noise detection disabled")
        #time.sleep(1)
        #loop.quit()

class NoiseHandler(BaseHTTPRequestHandler):
    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_GET(self):
        global recorder
        global noiseDetector
        global httpd
        global loop
        syslog.syslog("Controller received a request - " + self.path)
        query = urlparse(self.path).query
        query_components = dict(qc.split("=") for qc in query.split("&"))
        message = "Invalid request"
        if 'start_rec' in query_components and query_components['start_rec'] == 'true':
            if not recorder == None:
                message = "Recording already in progress"
            else:
                rec_id = query_components['rec_id']
                message = "Started recording"
                recorder = NoiseRecorder(rec_id)
                thread.start_new_thread(recorder.start, ())
        if 'stop_rec' in query_components and query_components['stop_rec'] == 'true':
            if not recorder == None:
                message = "Stopped recording"
                recorder.stop()
                recorder = None
            else:
                message = "Recording not in progress"
        if 'shutdown' in query_components and query_components['shutdown'] == 'true':
            if not recorder == None:
                message = "Stopped recording"
                recorder.stop()
                recorder = None
            # TODO: Shutdown gracefully
            noiseDetector.shutdown = True
            thr = threading.Thread(target=stop_listener)
            thr.start()
            #httpd.shutdown()
            message = "Shutting down"
            loop.quit()
        self._set_headers()
        self.wfile.write("<html><body><h1>" + message + "</h1></body></html>")


class NoiseRecorder:
    def __init__(self, rec_id):
        self.rec_id = rec_id
        self.target_dir = "/var/lib/motion"
        pl_string = "alsasrc device=plug:dsnooper ! wavenc ! filesink location=\"{}/{}.wav\"".format(self.target_dir, self.rec_id)
        self.pipeline = Gst.parse_launch(pl_string)
        self.playmode = True

    def start(self):
        self.start_time = datetime.datetime.utcnow()
        self.pipeline.set_state(Gst.State.PLAYING)
        syslog.syslog("Started recording audio")
        while self.playmode:
            time.sleep(1)
        time.sleep(1)
        loop.quit()

    def stop(self):
        # Stop recording
        self.pipeline.set_state(Gst.State.READY)
        self.end_time = datetime.datetime.utcnow()
        # TODO: Output the duration
        syslog.syslog("Stopped recording audio")
        new_name = self.rec_id
        if new_name.startswith('.'):
            new_name = new_name[1:]
        if not os.path.isfile(self.target_dir + "/" + self.rec_id + ".wav"):
            syslog.syslog("WARNING - Audio file missing: " + self.target_dir + "/" + self.rec_id + ".wav")
            os.rename('{}/{}.mkv'.format(self.target_dir, self.rec_id), '{}/{}.mkv'.format(self.target_dir, new_name))
            os.remove('{}/{}.log'.format(self.target_dir, self.rec_id))
        elif os.path.getsize(self.target_dir + "/" + self.rec_id + ".wav") == 0:
            syslog.syslog("WARNING - Audio file has 0 bytes: " + self.target_dir + "/" + self.rec_id + ".wav")
            os.rename('{}/{}.mkv'.format(self.target_dir, self.rec_id), '{}/{}.mkv'.format(self.target_dir, new_name))
            os.remove('{}/{}.wav'.format(self.target_dir, self.rec_id))
            os.remove('{}/{}.log'.format(self.target_dir, self.rec_id))
        else:
            try:
            # Combine the video and audio
                subprocess.check_call("ffmpeg -hide_banner -loglevel quiet -i " + self.target_dir + "/" + self.rec_id + ".mkv -itsoffset 0.5 -i " + self.target_dir + "/" + self.rec_id + ".wav -c copy -shortest " + self.target_dir + "/" + self.rec_id + "_joined.mkv", shell=True)
                # Delete the unwanted files
                os.remove('{}/{}.mkv'.format(self.target_dir, self.rec_id))
                os.remove('{}/{}.wav'.format(self.target_dir, self.rec_id))
                os.remove('{}/{}.log'.format(self.target_dir, self.rec_id))
                os.rename('{}/{}_joined.mkv'.format(self.target_dir, self.rec_id), '{}/{}.mkv'.format(self.target_dir, new_name))
            except:
                syslog.syslog("Failed to combine audio and video files")


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
