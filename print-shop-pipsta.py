#!/usr/bin/env python
#
# PrintShopPrint.py
#
# Original Name - BasicPrint.py
# Copyright (c) 2014 Able Systems Limited. All rights reserved.
#
# Modified by Garry Lancaster 2019 to perform as a simple wifi print server
# on port 65432 for the ZX Spectrum Next.
#
# Modified by D. 'Xalior' Rimron-Soutter 2019 to perform as a slightly more
# complex wifi print server, also on port 65432, compatible with Garry's
# version, still for the ZX Spectrum Next.
from __future__ import print_function

HOST = ''
PORT = 65432

'''PrintShopPipsta is provided as-is, and is for demonstration
purposes only. Stale Pixels, or Xalior takes no responsibility
for any system implementations based on this code.

Copyright (c) 2014 Able Systems Limited. All rights reserved.
Copyright (c) 2019 Stale Pixels.         Some rights reserved.

'''
import argparse
import logging
import platform
import struct
import sys
import time
import Image

import usb.core
import usb.util

import socket

from ZXGraphics import ZXScreen, ZXImage
from array import array
from bitarray import bitarray

# Printer commands
SET_FONT_MODE_3 = b'\x1b!\x03'
SET_LED_MODE = b'\x1bX\x2d'
FEED_PAST_CUTTER = b'\n' * 5
SELECT_SDL_GRAPHICS = b'\x1b*\x08'

# USB specific constant definitions
PIPSTA_USB_VENDOR_ID = 0x0483
PIPSTA_USB_PRODUCT_ID = 0xA19D
AP1400_USB_PRODUCT_ID = 0xA053
AP1400V_USB_PRODUCT_ID = 0xA19C

valid_usb_ids = {PIPSTA_USB_PRODUCT_ID, AP1400_USB_PRODUCT_ID, AP1400V_USB_PRODUCT_ID}

class printer_finder(object):
    def __call__(self, device):
        if device.idVendor != PIPSTA_USB_VENDOR_ID:
            return False

        return True if device.idProduct in valid_usb_ids else False


DOTS_PER_LINE = 384
BYTES_PER_DOT_LINE = DOTS_PER_LINE/8
USB_BUSY = 66

#import struct
MAX_PRINTER_DOTS_PER_LINE = 384
LOGGER = logging.getLogger('image_print.py')


PRINT_MODE_NEW = 0              ## Waiting for a new command
PRINT_MODE_TXT = 1              ## Printing Text
PRINT_MODE_SCR = 2              ## Printing a SCR
PRINT_MODE_NXI = 3              ## Printing a NXI

PRINT_MODE_CMD = -1             ## Processing a Command


valid_usb_ids = {PIPSTA_USB_PRODUCT_ID, AP1400_USB_PRODUCT_ID, AP1400V_USB_PRODUCT_ID}


def setup_logging():
    '''Sets up logging for the application.'''
    LOGGER.setLevel(logging.INFO)

    file_handler = logging.FileHandler('mylog.txt')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(fmt='%(asctime)s %(message)s',
                                                datefmt='%d/%m/%Y %H:%M:%S'))

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)

    LOGGER.addHandler(file_handler)
    LOGGER.addHandler(stream_handler)


def setup_usb():
    """Connects to the 1st Pipsta found on the USB bus"""
    # Find the Pipsta's specific Vendor ID and Product ID (also known as vid
    # and pid)
    dev = usb.core.find(custom_match=printer_finder())
    if dev is None:  # if no such device is connected...
        raise IOError('Printer not found')  # ...report error

    try:
        dev.reset()

        # Initialisation. Passing no arguments sets the configuration to the
        # currently active configuration.
        dev.set_configuration()
    except usb.core.USBError as err:
        raise IOError('Failed to configure the printer', err)

    # Get a handle to the active interface
    cfg = dev.get_active_configuration()

    interface_number = cfg[(0, 0)].bInterfaceNumber
    usb.util.claim_interface(dev, interface_number)
    alternate_setting = usb.control.get_interface(dev, interface_number)
    intf = usb.util.find_descriptor(
        cfg, bInterfaceNumber=interface_number,
        bAlternateSetting=alternate_setting)

    ep_out = usb.util.find_descriptor(
        intf,
        custom_match=lambda e:
        usb.util.endpoint_direction(e.bEndpointAddress) ==
        usb.util.ENDPOINT_OUT
    )

    if ep_out is None:  # check we have a real endpoint handle
        raise IOError('Could not find an endpoint to print to')

    return ep_out, dev


def convert_image(image):
    """Takes the bitmap and converts it to PIPSTA 24-bit image format"""
    imagebits = bitarray(image.getdata(), endian='big')
    imagebits.invert()
    return imagebits.tobytes()

def parse_arguments():
    """Parse the arguments passed to the script looking for a font file name."""
    parser = argparse.ArgumentParser()
    parser.add_argument('font', help='Optional 1bit-mapped font',
                        nargs='*')
    args = parser.parse_args()

    return args

def print_image(device, ep_out, data):
    '''Reads the data and sends it a dot line at once to the printer
    '''
    LOGGER.debug('Start print')
    try:
        ep_out.write(SET_FONT_MODE_3)
        cmd = struct.pack('3s2B', SELECT_SDL_GRAPHICS,
                          (DOTS_PER_LINE / 8) & 0xFF,
                          (DOTS_PER_LINE / 8) / 256)
        # Arbitrary command length, set to minimum acceptable 24x8 dots this figure
        # should give mm of print
        lines = len(data) // BYTES_PER_DOT_LINE
        for line in range(0, lines):
            start = line * BYTES_PER_DOT_LINE
            # intentionally +1 for slice operation below
            end = start + BYTES_PER_DOT_LINE
            # ...to end (end not included)
            ep_out.write(b''.join([cmd, data[start:end]]))

            res = device.ctrl_transfer(0xC0, 0x0E, 0x020E, 0, 2)
            while res[0] == USB_BUSY:
                time.sleep(0.01)
                res = device.ctrl_transfer(0xC0, 0x0E, 0x020E, 0, 2)
                LOGGER.debug('End print')
    finally:
        #ep_out.write(RESTORE_DARKNESS)
        pass

def main():
    """The main loop of the application.  Wrapping the code in a function
    prevents it being executed when various tools import the code."""
    # This script is written using the PIL which requires Python 2
    if sys.version_info[0] != 2:
        sys.exit('This application requires python 2.')

    if platform.system() != 'Linux':
        sys.exit('This script has only been written for Linux')

    args = parse_arguments()
    setup_logging()
    usb_out, device = setup_usb()
    usb_out.write(SET_LED_MODE + b'\x01')
    
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((HOST,PORT))

    try:
        while True:
            s.listen(0)
            print('Listening with timeout: '+ s.gettimeout().__str__())
            conn, addr = s.accept()
            print('Connected by', addr)
            # Our "default" variables, reset per connection...
            mode = PRINT_MODE_NEW
            size = 0
            dither = 0
            rotate = 0
            cmd = ""
            input_buffer = array('B')
            while True:
                data = conn.recv(65536)
                if not data:
                    break


                for byte in data:
                    done = False
                    if mode is PRINT_MODE_CMD:                  # We're currently processing commands
                        if byte == chr(13):                              # Finish processing command
                            print("RECV: EoCOMMAND ("+cmd+")")

                            if cmd == '.SCR':
                                mode = PRINT_MODE_SCR                   # Engage SCR Printer
                                print(' CMD! Enable SCR Mode')
                                done = True
                            elif  cmd == '.NXI':
                                mode = PRINT_MODE_NXI                   # Engage SCR Printer
                                print(' CMD! Enable NXI Mode')
                                done = True
                            elif cmd.startswith("SET"):
                                if "dither" in cmd:
                                    print(' CMD! Enable DITHERing')
                                    dither = 1
                                    mode = PRINT_MODE_NEW
                                elif "rotate" in cmd:
                                    print(' CMD! Enable ROTATE')
                                    rotate = 1
                                    mode = PRINT_MODE_NEW
                            else:
                                mode = PRINT_MODE_NEW                   # Wait for Next Instruction

                            cmd = ""
                        else:
                            cmd = cmd + byte

                    elif not mode:                              # First Packet -- decide how to proceed
                        if byte == chr(0):
                            print(' CMD! Enable Command Mode')
                            mode = PRINT_MODE_CMD               # Command Mode
                        else:
                            print('RECV: Detected Plain Text File')
                            mode = PRINT_MODE_TXT               # Classic Printer Mode

                    if not done:
                        if mode == PRINT_MODE_TXT:                          # Classic Textmode Printer
                            # Print a char at a time and check the printers buffer isn't full
                            usb_out.write(byte)    # write all the data to the USB OUT endpoint
                            #
                            res = device.ctrl_transfer(0xC0, 0x0E, 0x020E, 0, 2)
                            while res[0] == USB_BUSY:
                               time.sleep(0.01)
                               res = device.ctrl_transfer(0xC0, 0x0E, 0x020E, 0, 2)
                        elif mode == PRINT_MODE_SCR \
                            or mode == PRINT_MODE_NXI:                      # .FILE appendnd to buffer
                            input_buffer.append(ord(byte))
                    size = size + 1

            print("DIAG: Total Size "+size.__str__()+"bytes, input_buffer "+input_buffer.__len__().__str__())

            if mode == PRINT_MODE_SCR:
                screen = ZXScreen()
                screen.parse(input_buffer)
                if dither == 0:
                    img = screen.mono()
                else:
                    img = screen.dither()
                print(rotate)
                if rotate == 1:
                    print("ROTATED IT")
                    img = img.rotate(90, 0, 1)
                img.save("demo.png")
                newFile = open("demo.scr", "wb")
                newFileByteArray = bytearray(input_buffer)
                newFile.write(newFileByteArray)
                newFile.close()

                # From http://stackoverflow.com/questions/273946/
                # /how-do-i-resize-an-image-using-pil-and-maintain-its-aspect-ratio
                wpercent = (DOTS_PER_LINE / float(img.size[0]))
                hsize = int((float(img.size[1]) * float(wpercent)))
                img = img.resize((DOTS_PER_LINE, hsize), Image.NONE)

                print_data = convert_image(img)
                usb_out.write(SET_LED_MODE + b'\x00')
                print_image(device, usb_out, print_data)
                usb_out.write(FEED_PAST_CUTTER)
                # Ensure the LED is not in test mode
                usb_out.write(SET_LED_MODE + b'\x00')

            elif mode == PRINT_MODE_NXI:
                screen = ZXImage()
                screen.parse(input_buffer)
                if dither == 0:
                    img = screen.mono()
                else:
                    img = screen.dither()
                print(rotate)
                if rotate == 1:
                    print("ROTATED IT")
                    img = img.rotate(90, 0, 1)
                img.save("demo.png")
                newFile = open("demo.scr", "wb")
                newFileByteArray = bytearray(input_buffer)
                newFile.write(newFileByteArray)
                newFile.close()

                # From http://stackoverflow.com/questions/273946/
                # /how-do-i-resize-an-image-using-pil-and-maintain-its-aspect-ratio
                wpercent = (DOTS_PER_LINE / float(img.size[0]))
                hsize = int((float(img.size[1]) * float(wpercent)))
                img = img.resize((DOTS_PER_LINE, hsize), Image.NONE)

                print_data = convert_image(img)
                usb_out.write(SET_LED_MODE + b'\x00')
                print_image(device, usb_out, print_data)
                usb_out.write(FEED_PAST_CUTTER)
                # Ensure the LED is not in test mode
                usb_out.write(SET_LED_MODE + b'\x00')
    finally:
        usb.util.dispose_resources(device)

# Ensure that BasicPrint is ran in a stand-alone fashion (as intended) and not
# imported as a module. Prevents accidental execution of code.
if __name__ == '__main__':
    main()

