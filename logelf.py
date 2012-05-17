#!/usr/bin/python

import pika
import sys
import ConfigParser

usage = """logelf -c CONFIG_FILE
"""

def read_config(config_file, section, var):
    "Read config and return value"

    config = ConfigParser.RawConfigParser()
    config.read(config_file)

    value = config.get(section, var)

    return value


def main():
    "Main function"
    
    if len(sys.argv) == 3 and "-c" in sys.argv:
        if os.path.exits(sys.argv[2]):
            config_file = sys.argv[2]
            syslog_fifo = read_config((config_file, "syslog", "fifo")
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
        else:
            raise IOError, err:
                print "Exception: %s" % (err)
    else:
        raise ValueError(usage)

main()
