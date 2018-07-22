#!/usr/bin/python
import sys
import Adafruit_DHT
import syslog

pin = 24
humidity, temperature = Adafruit_DHT.read_retry(Adafruit_DHT.DHT22, pin)
if humidity is None or temperature is None:
    humidity = 0
    temperature = 0
    syslog.syslog("Unable to read temperature and humidity")
print('{0:0.1f} {1:0.1f}'.format(temperature, humidity))
