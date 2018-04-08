# Fruitnanny

Fruitnanny is a DIY baby monitor built on the Raspberry Pi. With the recommended hardware, along with the configuration files and front-end application contained in this repository, a live audio/video WebRTC stream can be presented in the browser.

### Current Features
* Live audio/video baby monitor
* Temperature/humidity readings (with DHT22 sensor installed)
* Stream in any browser that supports [WebRTC](https://caniuse.com/#search=webrtc)

### Upcoming Features
* Updated UI built on ReactJS
* Track baby's naps with a nap timer, and display data on an interactive chart

## Recommended Hardware
* Raspberry Pi 3 (running Raspbian Stretch)
* NoIR v2 Camera Module
* Infrared LED Lights
* DHT22 Temperature/Humidity Sensor
* USB Microphone

## Setup

1. Fruitnanny was developed by [Dmitry Ivanov](https://ivadim.githib.io). Dmitry lists instructions on setting up the Pi and hardware peripherals on his [blog](https://ivadim.github.io/2017-08-21-fruitnanny/#build-guide). Follow these until you reach Step 2: Basic configuration, then stop and return here to complete the software installation.

2. With your Pi up and running, we first need to enable the camera and resize the partition. Enter the command `sudo raspi-config`. Select `5 Interfacing options` followed by `P1 Camera` and enable it. Back in the main menu, selct `7 Advanced Options`, then `S1 Expand Filesystem`. While you're here, you may also want to change the default password. When you're finished, reboot your Pi.

3. After booting back up, enter the following commands:  

    ```bash
    sudo apt-get -y install git
    cd /opt
    sudo mkdir fruitnanny
    sudo chown pi:pi fruitnanny
    git clone https://github.com/cryptotech23/fruitnanny
    cd fruitnanny
    sudo ./install.sh
    ```  

    The [installation script](install.sh) was created by [Alex Russell](https://github.com/alexjrussell). It installs all of the required software to get Fruitnanny up and running. During installation, you will be prompted for baby's name and birthdate, as well as the desired temperature measurement (F or C). The rest of the installation will take about 15-20 minutes. Towards the end, you will be prompted to set a password for Fruitnanny's web interface.

4. Reboot your Pi, then open a browser and navigate to the Pi's IP address. If all went well, you should be able to enter "fruitnanny" as your username and the password you selected to gain access to a fully functional baby monitor!
