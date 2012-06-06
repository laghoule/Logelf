#!/usr/bin/python

# Written by Pascal Gauthier <pgauthier@onebigplanet.com>
# Copyright GPLv3
# 05.16.2012 

import thread
from socket import gethostname
import gevent
from gevent import socket
import string
import json
import time
import pika
import stat
import sys
import os
import ConfigParser
import argparse

__metaclass__ = type

class SendLog:
    "Class of syslog log"

    def __init__(self, logelf_conf, amqp_server, virtualhost, credentials, 
            amqp_exchange, ssl, syslog_fifo, syslog_socket, socket_buffer): 
        "Class initialisation"

        # Global class var
        self.facilities = ("kernel", "user-level", 
                "mail system", "system daemons", 
                "security/authorization",
                "syslogd generated message", 
                "line printer subsystem", "network news subsystem",
                "UUCP subsystem", "clock related", 
                "security/authorization", "FTP daemon", 
                "NTP subsystem", "log audit", "log alert", 
                "clock related", "local use 0", "local use 1", 
                "local use 2", "local use 2", "local use 3", 
                "local use 4", "local use 5", "local use 6", "local use 7")
        self.hostname = gethostname()
        self.syslog_fifo = syslog_fifo
        self.syslog_socket = syslog_socket
        self.socket_buffer = socket_buffer
        self.amqp_exchange = amqp_exchange
        self.logelf_conf = logelf_conf


        if self.logelf_conf.get('loadavg') == "on":
            self.loadavg_file = open('/proc/loadavg', 'r', 0)
    
        if self.logelf_conf.get('memstat') == "on":
            self.memstat_file = open('/proc/meminfo', 'r', 0)

        # /proc/kmsg initialisation
        self.kmsg_file = open('/proc/kmsg', 'r', 0)

        # Our local fifo initialisation
        if stat.S_ISFIFO(os.stat(syslog_fifo).st_mode):
            try:
                fd = os.open(syslog_fifo, os.O_RDWR | os.O_NONBLOCK, 0)
                self.fifo_file = os.fdopen(fd,'w', 0)
            except Exception, err:
                print "Fifo exception: %s" % (err)
                sys.exit(1)
        else:
            print "%s is not a fifo file" % (syslog_fifo)
            sys.exit(1)

        # /dev/log initialisation
        try:
            self.devlog_socket = socket.socket(socket.AF_UNIX, 
                                            socket.SOCK_DGRAM)
            self.devlog_socket.bind(syslog_socket)
        except Exception, err:
            print "Socket exception: %s" % (err)
            sys.exit(1)

        # AMQP initialisation
        while True:
            try:
                if ssl.get('enable') == "on":
                    #self.ssl_options = {'ca_certs': ssl_info.get('cacert'), 
                    #                    'certfile': ssl_info.get('cert'), 
                    #                    keyfile': ssl_info.get('key')}
                    #self.connection = pika.BlockingConnection(pika.ConnectionParameters(host=amqp_server,
                    #                        credentials=credentials, virtual_host=virtualhost,
                    #                        ssl=True, ssl_options=self.ssl_options))
                    print """AMQPS support broken right now (blame pika)... 
                            fallback to normal AMQP"""
                    self.connection = pika.BlockingConnection(pika.ConnectionParameters(host=amqp_server,
                                             credentials=credentials, virtual_host=virtualhost))
                    break
                elif ssl.get('enable') == "off":
                    self.connection = pika.BlockingConnection(pika.ConnectionParameters(host=amqp_server,
                                             credentials=credentials, virtual_host=virtualhost))
                    break
            except Exception, err:
                print "Exception: %s, will retry in 5 sec.." % (err)
                time.sleep(5)

        self.channel = self.connection.channel()

    def process_log(self, syslog_type, amqp_rkey):
        "Process the log, and send to AMQP broker"

        while True:
            try:
                if syslog_type == "kernel":
                    data = self.kmsg_file.readline()
                elif syslog_type == "system":
                    data,addr = self.devlog_socket.recvfrom(self.socket_buffer)
                else:
                    raise Exception('Wrong type, must be "system" or "kernel"')
                    sys.exit(1)
                # Send to gelfify 
                gelf_msg = self.gelfify(syslog_type, data)
                # Send to local fifo
                self.__write_to_fifo__(gelf_msg)
                # Send to AMQP broker 
                self.__send_to_broker__(amqp_rkey, gelf_msg)
            except KeyboardInterrupt:
                print "Keyboard interruption"
                self.close()
                break

    def __read_loadavg__(self):
        "Read /proc/loadavg"

        self.loadavg_file.seek(0)
        return self.loadavg_file.read().split() 

    def __read_memstat__(self):
        "Read /prod/meminfo"

        meminfo = [None, None]
        self.memstat_file.seek(0)

        for i in range(2):
            meminfo[i] = self.memstat_file.readline().split()[1]

        return meminfo

    def __write_to_fifo__(self, gelf_msg):
        "Write to a fifo file"

        # This is a kludge to clear the buffer of the fifo
        # If there is no consumer of the fifo, buffer will fill
        try:
            self.fifo_file.write(gelf_msg + "\n")
        except IOError:
            fd = os.open(self.syslog_fifo, os.O_RDWR | os.O_NONBLOCK)
            flush_syslog_fifo = os.fdopen(fd, 'r')
            flush_syslog_fifo.read()
            flush_syslog_fifo.close()
        except Exception, err:
            print "Exception: %s" % (err)
            sys.exit(1)

    def __send_to_broker__(self, amqp_rkey, amqp_msg):
        "Send messages to AMQP broker"
        
        self.channel.basic_publish(exchange=self.amqp_exchange, 
                        routing_key=amqp_rkey, body=amqp_msg)
        #try:
        #    self.channel.basic_publish(exchange=self.amqp_exchange,
        #                    routing_key=amqp_rkey, body=amqp_msg) 
        #except Exception, err:
        #    print "Exception: %s" % (err)
        #    sys.exit(1)

    def gelfify(self, syslog_type, syslog_msg):
        "Gelfify the syslog messages"
        
        msg1 = syslog_msg.replace("<", "")
        msg2 = msg1.replace(">", " ")
        msg = msg2.split()

        self.priority = msg[0]
        self.facility = int(self.priority) / 8
        self.severity = int(self.priority) - self.facility * 8
        self.header = ""

        if syslog_type == "system":
            self.header_short = " ".join(msg[4:])
        elif syslog_type == "kernel":
            self.header_short = " ".join(msg[1:])
        else:
            raise Exception('Wrong type, must be "system" or "kernel"')

        self.header = self.header_short
        if self.logelf_conf.get('loadavg') == "on":
            loadavg = self.__read_loadavg__()
            if len(loadavg) >= 3:
                self.header += "\nLoad average: [%s] [%s] [%s]" % (loadavg[0],
                                loadavg[1], loadavg[2])

        if self.logelf_conf.get('memstat') == "on":
            memstat = self.__read_memstat__()
            if len(memstat) == 2:
                self.header += "\nMemory stats: [Free %s] [Used %s]" % (memstat[0], memstat[1])

        self.gelf_msg = {'version': "1", 'timestamp': time.asctime(), 
                        'short_message': self.header_short,
                        'full_message': self.header , 'host': self.hostname,
                        'level': self.severity, 
                        'facility': self.facilities[int(self.facility)]}

        return json.dumps(self.gelf_msg)

    def run(self, amqp_rkey):
        "Run the show"

        # Separate thread to read /proc/kmsg
        thread.start_new_thread(self.process_log, ('kernel', amqp_rkey,))
        # Read /dev/log
        self.process_log('system', amqp_rkey)
    
    def close(self):
        "Close the socket and fifo"

        # Close /proc/_proc_file
        if self.logelf_conf.get('loadavg') == "on":
            self.loadavg_file.close()

        if self.logelf_conf.get('memstat') == "on":
            self.memstat_file.close()

        # Exit the thread reading /proc/kmsg
        thread.exit()

        # Close /proc/kmsg
        self.kmsg_file.close()

        # Close localfifo
        self.fifo_file.close()

        # Close socket
        self.devlog_socket.close()
        os.remove(self.syslog_socket)


def main():
    "Main function"

    parser = argparse.ArgumentParser()
    parser.add_argument("config", action="store",
                help="path to config FILE",  metavar="CONFIG_FILE")

    args = parser.parse_args()

    config_fh = open(args.config)
    config = ConfigParser.RawConfigParser()
    config.readfp(config_fh)

    # Config var
    logelf_loadavg = config.get("logelf", "loadavg")
    logelf_memstat = config.get("logelf", "memstat")
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

    # Config dict
    logelf_conf = {'loadavg': logelf_loadavg, 
            'memstat': logelf_memstat}
    ssl = {'enable': ssl_enable, 'cacert': cacertfile, 
            'cert': certfile, 'key': keyfile}

    # Credential for AMQP broker
    credentials = pika.PlainCredentials(username, password)

    log = SendLog(logelf_conf, amqp_server, virtualhost,
            credentials, amqp_exchange, ssl, syslog_fifo, 
            syslog_socket, socket_buffer)

    log.run("log")

if __name__ == '__main__':
    main()
