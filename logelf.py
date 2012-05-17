#!/usr/bin/python

# Written by Pascal Gauthier <pgauthier@onebigplanet.com>
# Copyright GPLv3
# 05.16.2012 

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
    def __init__(self, amqp_server, virtualhost, credentials, amqp_exchange, ssl, syslog_socket):
        self.mysocket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.mysocket.bind(syslog_socket)

    def read(self, socket_buffer):
        "Read input from syslog socket" 
        
        self.data,self.addr = self.mysocket.recvfrom(socket_buffer)
        #print "\nReceived message '", self.data,"'"
        #while True:
        #    self.data,self.addr = self.mysocket.recvfrom(socket_buffer)
        #    if not self.data:
        #        print "Client has exited!"
        #        break
        #    else:
        #        print "\nReceived message '", self.data,"'"
        return self.data

    def send(self, socket_buffer):
        "Send syslog messages to AMQP server"

        while True:
            msg = self.read(socket_buffer)
            print msg

    def gelfify(self):
        pass


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
        
        log = Log(amqp_server, virtualhost, credentials, amqp_exchange, ssl, syslog_socket) 
        #result = log.read(socket_buffer)
        result = log.send(socket_buffer)

    else:
        raise ValueError(usage)

main()
