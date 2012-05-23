#!/usr/bin/python

# Written by Pascal Gauthier <pgauthier@onebigplanet.com>
# Copyright GPLv3
# 05.16.2012 

import gevent
from gevent import socket
import json
import time
import pika
import stat
import sys
import os
import ConfigParser
import optparse

usage = """logelf -c CONFIG_FILE
"""

__metaclass__ = type

class Log:
    "Class of syslog log"

    def __init__(self, amqp_server, virtualhost, credentials, amqp_exchange, ssl, syslog_fifo, syslog_socket, socket_buffer): 
        "Class initialisation"

        # Global class var
        self.facilities = ("kernel messages", "user-level messages", 
                "mail system", "system daemons", 
                "security/authorization  messages",
                "messages generated internally by syslogd", 
                "line printer subsystem", "network news subsystem",
                "UUCP subsystem", "clock related", 
                "security/authorization messages", "FTP daemon", 
                "NTP subsystem", "log audit", "log alert", 
                "clock related", "local use 0", "local use 1", 
                "local use 2", "local use 2", "local use 3", 
                "local use 4", "local use 5", "local use 6", "local use 7")
        self.hostname = socket.gethostname()
        self.syslog_fifo = syslog_fifo
        self.syslog_socket = syslog_socket
        self.socket_buffer = socket_buffer
        self.amqp_exchange = amqp_exchange

        # Fifo initialisation
        if stat.S_ISFIFO(os.stat(syslog_fifo).st_mode):
            try:
                self.syslog_fifo = open(syslog_fifo, 'w+', 0)
            except Exception, err:
                print "Fifo exception: %s" % (err)
                sys.exit(1)
        else:
            print "%s is not a fifo file" % (syslog_fifo)
            sys.exit(1)

        # Socket initialisation
        try:
            self.mysocket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            self.mysocket.bind(syslog_socket)
        except Exception, err:
            print "Socket exception: %s" % (err)
            sys.exit(1)

        # AMQP initialisation
        while True:
            try:
                if ssl.get('enable') == "on":
                    #self.ssl_options = {'ca_certs': ssl_info.get('cacert'), 'certfile': ssl_info.get('cert'), keyfile': ssl_info.get('key')}
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
                gelf_msg = self.gelfify(self.data)
                print gelf_msg
            except KeyboardInterrupt:
                print "Keyboard interruption"
                self.close()
                break

    def __write_to_fifo__(self, gelf_msg):
        "Write to a fifo file"

        self.syslog_fifo.write(gelf_msg + "\n")

    def send(self, amqp_rkey):
        "Send syslog messages to AMQP server"

        while True:
            try:
                self.data,self.addr = self.mysocket.recvfrom(self.socket_buffer)
                # Send to gelfify 
                gelf_msg = self.gelfify(self.data)
                print gelf_msg
                # Send to fifo
                self.__write_to_fifo__(gelf_msg)
                # Send to amqp
                self.channel.basic_publish(exchange=self.amqp_exchange, routing_key=amqp_rkey, body=gelf_msg) 
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
        self.short_msg = msg[4].replace(":", "")
        self.header = " ".join(msg[4:])

        self.gelf_msg = {'version': "1", 'timestamp': self.time, 'short_message': self.short_msg,
                        'full_message': self.header , 'host': self.hostname, 'level': self.severity,
                        'facility': self.facilities[int(self.facility)]}

        return json.dumps(self.gelf_msg)
    
    def close(self):
        "Close the socket and fifo"

        # Close fifo
        self.syslog_fifo.close()

        # Close socket
        self.mysocket.close()
        os.remove(self.syslog_socket)


def main():
    "Main function"

    parser = optparse.OptionParser()
    parser.add_option("-c", "--config", dest="config",
                  help="path to config FILE", metavar="FILE")
    (options, args) = parser.parse_args()
    if not options.config:
        print 'missing --config'
        sys.exit(1)

    config_fh = open(options.config)
    config = ConfigParser.RawConfigParser()
    config.readfp(config_fh)

    syslog_fifo = config.get("syslog", "fifo")
    syslog_socket = config.get("syslog", "socket")
    socket_buffer = config.getint("syslog", "buffer")
    amqp_server = config.get("amqp", "server")
    amqp_exchange = config.get("amqp", "exchange")
    amqp_rkey = config.get("amqp", "routing_key")
    virtualhost = config.get("amqp", "virtualhost")
    username = config.get("amqp", "username")
    password = config.get("amqp", "password")
    ssl_enable = config.get("ssl", "enable")
    cacertfile = config.get("ssl", "cacertfile")
    certfile = config.get("ssl", "certfile")
    keyfile = config.get("ssl", "keyfile")
    ssl = { 'enable': ssl_enable, 'cacert': cacertfile, 'cert': certfile, 'key': keyfile }
    credentials = pika.PlainCredentials(username, password)

    log = Log(amqp_server, virtualhost, credentials, amqp_exchange, ssl, syslog_fifo, syslog_socket, socket_buffer)
    log.send("log")

if __name__ == '__main__':
    main()
