#!/bin/bash

FN_REPO_URL=https://github.com/alexjrussell/fruitnanny
NGINX_VERSION=1.10.3

# Check we are root
if [ "$(whoami)" != "root" ]; then
    echo "You must be root to run this script"
    exit 1
fi

# Check the distribution and version
RECOMMENDED_DIST=0
if [ -f /etc/os-release ]; then
    . /etc/os-release
    if [ "$ID" == "raspbian" -a "$VERSION_ID" == "9" ]; then
        RECOMMENDED_DIST=1
    fi
fi
if [ "$RECOMMENDED_DIST" == "0" ]; then
    echo "WARNING - You are not using the the recommended distribution or version"
    echo "This script has only been tested with Raspbian 9 (stretch)"
    echo "Press enter to continue or Ctrl-C to abort"
    read
fi

echo "You need to have met the following pre-requisites before running this script:"
echo "- Enabled the camera"
echo "- Enlarged the root partition"

# Disable wifi power-save mode
echo "Disable wifi power save mode"
iw dev wlan0 set power_save off
echo "wireless-power off" >> /etc/network/interfaces

# Disable ipv6
echo "Disable ipv6"
cat >> /etc/modprobe.d/ipv6.conf <<EOF
alias ipv6 off
options ipv6 disable_ipv6=1
blacklist ipv6
EOF

# Update the package list
apt-get -y update

# Upgrade the Raspberry Pi’s firmware
apt-get -y install rpi-update
yes | rpi-update

# Install packages
apt-get -y install vim git nano emacs libraspberrypi-dev autoconf automake libtool pkg-config avahi-daemon\
    alsa-base alsa-tools alsa-utils build-essential python-dev python-pip python-alsaaudio

pip install xvfbwrapper

# Download & install nodejs
curl -sL https://deb.nodesource.com/setup_6.x | bash -
apt install -y nodejs

# Install nodejs process manager (PM2) for automatic nodejs app startup
npm install pm2 -g
sudo -u pi pm2 startup
env PATH=$PATH:/usr/bin /usr/lib/node_modules/pm2/bin/pm2 startup systemd -u pi --hp /home/pi
sudo -u pi pm2 save

apt-get -y install python-gst-1.0 python-gobject ffmpeg xvfb pulseaudio dbus-x11

# Install fruitnanny
cd /opt
git clone $FN_REPO_URL
chown -R pi:pi /opt/fruitnanny
# Configure fruitnanny
read -p "Enter your baby's name [Baby]: " baby_name
if [ "$baby_name" == "" ]; then
    baby_name=Baby
fi
read -p "Enter your baby's date of birth (yyyy-mm-dd): " baby_birthdate
# TODO: Validate birth date
read -p "Enter temperature unit (C/F) [C]: " temp_unit
# TODO: Validate temperature unit
if [ "$temp_unit" == "" ]; then
    temp_unit=C
fi
# Update /opt/fruitnanny/fruitnanny_config.js
sed -i "s/Matthew/${baby_name}/g" /opt/fruitnanny/fruitnanny_config.js
sed -i "s!2016-03-15!${baby_birthdate}!g" /opt/fruitnanny/fruitnanny_config.js
sed -i "s/\"temp_unit\": \"C\"/\"temp_unit\": \"${temp_unit}\"/g" /opt/fruitnanny/fruitnanny_config.js
cd /opt/fruitnanny
sudo -u pi npm install
sudo -u pi pm2 start /opt/fruitnanny/server/app.js --name="fruitnanny"

# Add the pi user to the pulse-access group
adduser pi pulse-access

# Install gstreamer plugins
apt-get -y install gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly gstreamer1.0-plugins-bad libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev gstreamer1.0-alsa

# Install gstreamer camera module
git clone https://github.com/thaytan/gst-rpicamsrc /tmp/gst-rpicamsrc
cd /tmp/gst-rpicamsrc
./autogen.sh --prefix=/usr --libdir=/usr/lib/arm-linux-gnueabihf/
make
make install

# Install motion
# TODO: install dependencies of the motion package
apt-get -y install motion
wget -O /tmp/motion.deb https://github.com/Motion-Project/motion/releases/download/release-4.1.1/pi_stretch_motion_4.1.1-1_armhf.deb
dpkg --install /tmp/motion.deb
# Install motion config and service
chown pi:pi /var/lib/motion
chmod a+rx /var/lib/motion
mv /etc/motion/motion.conf /etc/motion/motion.conf_old
ln -s /opt/fruitnanny/configuration/motion/motion.conf /etc/motion/motion.conf
update-rc.d motion disable
ln -s /opt/fruitnanny/configuration/systemd/motion.service /etc/systemd/system/
systemctl enable motion

#modprobe bcm2835-v4l2

# Install Janus WebRTC Gateway
apt-get -y install libmicrohttpd-dev libjansson-dev libnice-dev \
    libssl-dev libsrtp-dev libsofia-sip-ua-dev libglib2.0-dev \
    libopus-dev libogg-dev pkg-config gengetopt libsrtp2-dev

git clone https://github.com/meetecho/janus-gateway /tmp/janus-gateway
cd /tmp/janus-gateway
git checkout v0.2.5
sh autogen.sh
./configure --disable-websockets --disable-data-channels --disable-rabbitmq --disable-mqtt
make
make install

# Configure Janus using the files in /opt/fruitnanny/configuration/janus
ln -s /opt/fruitnanny/configuration/janus/janus.cfg /usr/local/etc/janus
ln -s /opt/fruitnanny/configuration/janus/janus.plugin.streaming.cfg /usr/local/etc/janus
ln -s /opt/fruitnanny/configuration/janus/janus.transport.http.cfg /usr/local/etc/janus

# Generate ssl certificates
cd /usr/local/share/janus/certs
openssl req -x509 -sha256 -nodes -days 365 -newkey rsa:2048 -subj "/CN=www.fruitnanny.com" -keyout mycert.key -out mycert.pem

# Enable access to GPIO without root
adduser pi gpio

# Install Adafruit DHT module
git clone https://github.com/adafruit/Adafruit_Python_DHT /tmp/Adafruit_Python_DHT
cd /tmp/Adafruit_Python_DHT
python setup.py install

# Install service files
ln -s /opt/fruitnanny/configuration/systemd/noise.service /etc/systemd/system/
ln -s /opt/fruitnanny/configuration/systemd/janus.service /etc/systemd/system/

# Install dbus config, to allow motion to communicate with the recording daemon
ln -s /opt/fruitnanny/configuration/dbus/org.freedesktop.fruitnanny.conf /etc/dbus-1/system.d/

# Enable services
systemctl enable noise
systemctl enable janus

# Install nginx & rtmp module from source
apt-get -y install build-essential libpcre3 libpcre3-dev libssl-dev unzip
wget -O /tmp/nginx.tgz http://nginx.org/download/nginx-$NGINX_VERSION.tar.gz
cd /opt
tar -xzf /tmp/nginx.tgz
wget -O /tmp/nginx-rtmp.zip https://github.com/arut/nginx-rtmp-module/archive/master.zip
unzip /tmp/nginx-rtmp.zip
cd /opt/nginx-$NGINX_VERSION
./configure --with-http_ssl_module --add-module=../nginx-rtmp-module-master
make
make install

# Configure the nginx service
update-rc.d nginx disable
ln -s /opt/fruitnanny/configuration/systemd/nginx.service /etc/systemd/system/

# Install the nginx config
mv /usr/local/nginx/conf/nginx.conf /usr/local/nginx/conf/nginx.conf_old
ln -s /opt/fruitnanny/configuration/nginx/nginx.conf /usr/local/nginx/conf/nginx.conf

# Configure the password
sh -c "echo -n 'fruitnanny:' >> /usr/local/nginx/conf/.htpasswd"
echo "Enter password for fruitnanny web application"
sh -c "openssl passwd -apr1 >> /usr/local/nginx/conf/.htpasswd"

systemctl enable nginx

echo "Installation successful - reboot to start Fruitnanny!"
