#!/usr/bin/env python

# Written by Pascal Gauthier <pgauthier@onebigplanet.com>
# Copyright GPLv3
# 05.16.2012 

import fcntl
import signal
import atexit
import daemon
import lockfile
import thread
import socket
import gevent
import geventdaemon
from gevent import socket
from socket import gethostname
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

class PidFile(object):
    """Context manager that locks a pid file.  Implemented as class
    not generator because daemon.py is calling .__exit__() with no parameters
    instead of the None, None, None specified by PEP-343.

    From: http://code.activestate.com/recipes/577911-context-manager-for-a-daemon-pid-file/"""
    # pylint: disable=R0903

    def __init__(self, path):
        self.path = path
        self.pidfile = None

    def __enter__(self):
        self.pidfile = open(self.path, "a+")
        try:
            fcntl.flock(self.pidfile.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            raise SystemExit("Already running according to " + self.path)
        self.pidfile.seek(0)
        self.pidfile.truncate()
        self.pidfile.write(str(os.getpid()))
        self.pidfile.flush()
        self.pidfile.seek(0)
        return self.pidfile

    def __exit__(self, exc_type=None, exc_value=None, exc_tb=None):
        try:
            self.pidfile.close()
        except IOError as err:
            # ok if file was just closed elsewhere
            if err.errno != 9:
                raise
        os.remove(self.path)


class SendLog:
    "SendLog Class object"

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
        self.syslog_fifo = syslog_fifo
        self.syslog_socket = syslog_socket
        self.socket_buffer = socket_buffer
        self.amqp_exchange = amqp_exchange
        self.logelf_conf = logelf_conf

        if self.logelf_conf.get('hostname') == "" or self.logelf_conf.get('hostname') == "off":
            self.hostname = gethostname()
        else:
            self.hostname = self.logelf_conf.get('hostname') 

        if self.logelf_conf.get('loadavg') == "on":
            self.loadavg_file = open('/proc/loadavg', 'r', 0)
    
        if self.logelf_conf.get('memstat') == "on":
            self.memstat_file = open('/proc/meminfo', 'r', 0)

        # /proc/kmsg initialisation
        self.kmsg_file = open('/proc/kmsg', 'r', 0)

        # Our local fifo initialisation
        if os.path.exists(self.syslog_fifo):
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
        else:
            # We create and open the syslog fifo
            os.mkfifo(self.syslog_fifo)
            fd = os.open(syslog_fifo, os.O_RDWR | os.O_NONBLOCK, 0)
            self.fifo_file = os.fdopen(fd,'w', 0)

        # AMQP initialisation
        while True:
            try:
                if ssl.get('enable') == "on":
                    #self.ssl_options = {'ca_certs': ssl_info.get('cacert'), 
                    #                    'certfile': ssl_info.get('cert'), 
                    #                    keyfile': ssl_info.get('key')}
                    #self.amqp_connection = pika.BlockingConnection(pika.ConnectionParameters(host=amqp_server,
                    #                        credentials=credentials, virtual_host=virtualhost,
                    #                        ssl=True, ssl_options=self.ssl_options))
                    print "AMQPS support broken right now..." 
                    self.amqp_connection = pika.BlockingConnection(pika.ConnectionParameters(host=amqp_server,
                                             credentials=credentials, virtual_host=virtualhost))
                    break
                elif ssl.get('enable') == "off":
                    self.amqp_connection = pika.BlockingConnection(pika.ConnectionParameters(host=amqp_server,
                                             credentials=credentials, virtual_host=virtualhost))
                    break
            except Exception, err:
                print "Exception: %s, will retry in 5 sec.." % (err)
                time.sleep(5)

        self.amqp_channel = self.amqp_connection.channel()

        # /dev/log initialisation
        # Must be the last one to initialise
        try:
            self.devlog_socket = socket.socket(socket.AF_UNIX,
                                            socket.SOCK_DGRAM)
            self.devlog_socket.bind(syslog_socket)
        except Exception, err:
            print "Socket exception: %s" % (err)
            sys.exit(1)


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
        
        self.amqp_channel.basic_publish(exchange=self.amqp_exchange, 
                        routing_key=amqp_rkey, body=amqp_msg)


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
        # Bug with python-daemon 
        #thread.exit()

        # Close /proc/kmsg
        # Bug with python-daemon + thread
        #self.kmsg_file.close()

        # Close localfifo
        self.fifo_file.close()

        # Close socket
        self.devlog_socket.close()
        os.remove(self.syslog_socket)
    
        print "Closing done..."


def main():
    "Main function"

    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", dest="config", action="store",
                default="/etc/logelf.conf", help="path to config FILE",
                metavar="CONFIG_FILE")

    args = parser.parse_args()

    config_fh = open(args.config)
    config = ConfigParser.RawConfigParser()
    config.readfp(config_fh)

    # Config var
    logelf_hostname = str(config.get("logelf", "hostname"))
    logelf_loadavg = config.get("logelf", "loadavg")
    logelf_memstat = config.get("logelf", "memstat")
    syslog_fifo = config.get("syslog", "fifo")
    syslog_socket = "/dev/log" 
    socket_buffer = 1024 
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
    logelf_conf = {'hostname': logelf_hostname,
            'loadavg': logelf_loadavg, 
            'memstat': logelf_memstat}
    ssl = {'enable': ssl_enable, 'cacert': cacertfile, 
            'cert': certfile, 'key': keyfile}

    # Credential for AMQP broker
    credentials = pika.PlainCredentials(username, password)

    # Daemonification
    stdout_file = open('/var/log/logelf.log', 'a', 0)
    context = geventdaemon.GeventDaemonContext(
                umask=022,
                monkey_greenlet_report=False,
                monkey=False,
                stdout=stdout_file,
                stderr=stdout_file,
                detach_process=False, # For debug purpose
                pidfile=PidFile("/var/run/logelf.pid")
                )

    with context:
        print "Initializing sendlog class"
        log = SendLog(logelf_conf, amqp_server, virtualhost,
                credentials, amqp_exchange, ssl, syslog_fifo, 
                syslog_socket, socket_buffer)

        # Signal trap for the DaemonContext
        context.signal_map = {
            signal.SIGTERM: log.close,
            signal.SIGHUP:  'terminate',
            }

        # Run at exit
        atexit.register(log.close)
    
        try:
            print "Running sendlong.run method"
            log.run("log")
        finally:
            print "Closing daemon..."
            context.close()
    

if __name__ == "__main__":
        main()
