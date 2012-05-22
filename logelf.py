#!/usr/bin/python

# Written by Pascal Gauthier <pgauthier@onebigplanet.com>
# Copyright GPLv3
# 05.16.2012 

import string
import zlib
import json
import time
import socket
import pika
import sys
import os
import ConfigParser

usage = """logelf -c CONFIG_FILE
"""

__metaclass__ = type

def read_config(config_file, section, var):
    "Read config and return value"

    config = ConfigParser.RawConfigParser()
    config.read(config_file)

    value = config.get(section, var)
    return value


class Log:
    "Class of syslog log"

    def __init__(self, amqp_server, virtualhost, credentials, amqp_exchange, ssl, syslog_socket, socket_buffer):
        "Class initialisation"

        # Global class var
        self.hostname = socket.gethostname()
        self.syslog_socket = syslog_socket
        self.socket_buffer = socket_buffer

        # Socket initialisation
        self.mysocket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.mysocket.bind(syslog_socket)

        # AMQP initialisation
        while True:
            try:
                if ssl.get('enable') == "on":
                    #self.ssl_options = { 'ca_certs': ssl_info.get('cacert'), 'certfile': ssl_info.get('cert'), 'keyfile': ssl_info.get('key') }
                    #self.connection = pika.BlockingConnection(pika.ConnectionParameters(host=amqp_server, credentials=credentials, virtual_host=virtualhost, ssl=True, ssl_options=self.ssl_options))
                    print "AMQPS support broken right now (blame pika)... fallback to normal AMQP"
                    self.connection = pika.BlockingConnection(pika.ConnectionParameters(host=amqp_server, credentials=credentials, virtual_host=virtualhost))
                    break
                elif ssl.get('enable') == "off":
                    self.connection = pika.BlockingConnection(pika.ConnectionParameters(host=amqp_server, credentials=credentials, virtual_host=virtualhost))
                    break
            except Exception, err:
                print "Exception: %s, will retry in 5 sec.." % (err)
                time.sleep(5)

        #self.connection.add_timeout(rpc_timeout, self.__on_timeout__)
        self.channel = self.connection.channel()

    def read(self):
        "Read input from syslog socket" 
        
        while True:
            try:
                self.data,self.addr = self.mysocket.recvfrom(self.socket_buffer)
                print "\nReceived message '", self.data,"'"
                self.gelfify(self.data)
            except KeyboardInterrupt:
                print "Keyboard interruption"
                self.close()
                break

    def send(self):
        "Send syslog messages to AMQP server"

        while True:
            try:
                self.data,self.addr = self.mysocket.recvfrom(self.socket_buffer)
                # send to gelfify 
                # send to amqp
            except KeyboardInterrupt:
                print "Keyboard interruption"
                self.close()
                break

    def gelfify(self, syslog_msg):
        "Gelfify the syslog messages"
        
        msg1 = syslog_msg.replace("<", "")
        msg2 = msg1.replace(">", " ")
        msg = msg2.split()

        self.priority = msg[0]
        self.facility = int(self.priority) / 8
        self.severity = int(self.priority) - self.facility * 8
        self.time = msg[1] + " " + msg[2] + " " + msg[3]
        # need to stringify
        self.header = msg[4:]

        self.gelf_msg = { 'version': "1", 'timestamp': self.time, 'short_message': "Syslog2Gelf", 'full_message': self.header , 'host': self.hostname, 'level': self.severity, 'facility': self.facility }
        print self.gelf_msg

        #return gelf_msg
    
    def close(self):
        "Close the socket"

        self.mysocket.close()
        os.remove(self.syslog_socket)


def main():
    "Main function"
    
    if len(sys.argv) == 3 and "-c" in sys.argv:
        if os.path.exists(sys.argv[2]):
            config_file = sys.argv[2]
            syslog_socket = read_config(config_file, "syslog", "socket")
            socket_buffer = int(read_config(config_file, "syslog", "buffer"))
            amqp_server = read_config(config_file, "amqp", "server")
            amqp_exchange = read_config(config_file, "amqp", "exchange")
            amqp_rkey = read_config(config_file, "amqp", "routing_key")
            virtualhost = read_config(config_file, "amqp", "virtualhost")
            username = read_config(config_file, "amqp", "username")
            password = read_config(config_file, "amqp", "password")
            ssl_enable = read_config(config_file, "ssl", "enable")
            cacertfile = read_config(config_file, "ssl", "cacertfile")
            certfile = read_config(config_file, "ssl", "certfile")
            keyfile = read_config(config_file, "ssl", "keyfile")
            ssl = { 'enable': ssl_enable, 'cacert': cacertfile, 'cert': certfile, 'key': keyfile }
            credentials = pika.PlainCredentials(username, password)
        else:
            err_msg = "File %s don't exist" % (sys.argv[2])
            raise IOError(err_msg)
        
        log = Log(amqp_server, virtualhost, credentials, amqp_exchange, ssl, syslog_socket, socket_buffer) 
        result = log.read()
        #result = log.send(socket_buffer)

    else:
        raise ValueError(usage)

main()
