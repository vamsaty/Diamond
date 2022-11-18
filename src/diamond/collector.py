# coding=utf-8

"""
The Collector class is a base class for all metric collectors.
"""

import os
import socket
import platform
from . import logging
import configobj
import time
import re
import subprocess

from diamond.metric import Metric
from diamond.utils.config import load_config
from .error import DiamondException

# Detect the architecture of the system and set the counters for MAX_VALUES
# appropriately. Otherwise, rolling over counters will cause incorrect or
# negative values.

if platform.architecture()[0] == '64bit':
    MAX_COUNTER = (2 ** 64) - 1
else:
    MAX_COUNTER = (2 ** 32) - 1

prefix = 'ts_stat.'


def get_hostname(config, method=None):
    """
    Returns a hostname as configured by the user
    """
    method = method or config.get('hostname_method', 'smart')

    # case insensitive method
    method = method.lower()

    if 'hostname' in config and method != 'shell':
        return config['hostname']

    if method in get_hostname.cached_results:
        return get_hostname.cached_results[method]

    if method == 'shell':
        if 'hostname' not in config:
            raise DiamondException(
                "hostname must be set to a shell command for"
                " hostname_method=shell")
        else:
            proc = subprocess.Popen(config['hostname'],
                                    shell=True,
                                    stdout=subprocess.PIPE)
            hostname = proc.communicate()[0].strip()
            if proc.returncode != 0:
                raise subprocess.CalledProcessError(proc.returncode,
                                                    config['hostname'])
            get_hostname.cached_results[method] = hostname
            return hostname

    if method == 'smart':
        hostname = get_hostname(config, 'fqdn_short')
        if hostname != 'localhost':
            get_hostname.cached_results[method] = hostname
            return hostname
        hostname = get_hostname(config, 'hostname_short')
        get_hostname.cached_results[method] = hostname
        return hostname

    if method == 'fqdn_short':
        hostname = socket.getfqdn().split('.')[0]
        get_hostname.cached_results[method] = hostname
        if hostname == '':
            raise DiamondException('Hostname is empty?!')
        return hostname

    if method == 'fqdn':
        hostname = socket.getfqdn().replace('.', '_')
        get_hostname.cached_results[method] = hostname
        if hostname == '':
            raise DiamondException('Hostname is empty?!')
        return hostname

    # THOUGHTSPOT_CUSTOMIZATION_BEGIN
    if method == 'host_ip':
        hostname = socket.gethostbyname(socket.getfqdn()).replace('.', '_')
        get_hostname.cached_results[method] = hostname
        if hostname == '':
            raise DiamondException('Hostip is empty?!')
        return hostname
    # THOUGHTSPOT_CUSTOMIZATION_END
    if method == 'fqdn_rev':
        hostname = socket.getfqdn().split('.')
        hostname.reverse()
        hostname = '.'.join(hostname)
        get_hostname.cached_results[method] = hostname
        if hostname == '':
            raise DiamondException('Hostname is empty?!')
        return hostname

    if method == 'uname_short':
        hostname = os.uname()[1].split('.')[0]
        get_hostname.cached_results[method] = hostname
        if hostname == '':
            raise DiamondException('Hostname is empty?!')
        return hostname

    if method == 'uname_rev':
        hostname = os.uname()[1].split('.')
        hostname.reverse()
        hostname = '.'.join(hostname)
        get_hostname.cached_results[method] = hostname
        if hostname == '':
            raise DiamondException('Hostname is empty?!')
        return hostname

    if method == 'hostname':
        hostname = socket.gethostname()
        get_hostname.cached_results[method] = hostname
        if hostname == '':
            raise DiamondException('Hostname is empty?!')
        return hostname

    if method == 'hostname_short':
        hostname = socket.gethostname().split('.')[0]
        get_hostname.cached_results[method] = hostname
        if hostname == '':
            raise DiamondException('Hostname is empty?!')
        return hostname

    if method == 'hostname_rev':
        hostname = socket.gethostname().split('.')
        hostname.reverse()
        hostname = '.'.join(hostname)
        get_hostname.cached_results[method] = hostname
        if hostname == '':
            raise DiamondException('Hostname is empty?!')
        return hostname

    if method == 'none':
        get_hostname.cached_results[method] = None
        return None

    raise NotImplementedError(config['hostname_method'])


get_hostname.cached_results = {}


def str_to_bool(value):
    """
    Converts string truthy/falsey strings to a bool
    Empty strings are false
    """
    if isinstance(value, str):
        value = value.strip().lower()
        if value in ['true', 't', 'yes', 'y']:
            return True
        elif value in ['false', 'f', 'no', 'n', '']:
            return False
        else:
            raise NotImplementedError("Unknown bool %s" % value)

    return value


class Collector(object):
    """
    The Collector class is a base class for all metric collectors.
    """

    def __init__(self, config=None, handlers=[], name=None, configfile=None):
        """
        Create a new instance of the Collector class
        """
        # Initialize Logger
        logging.captureWarnings(True)
        self.log = logging.getLogger('diamond')
        # Initialize Members
        if name is None:
            self.name = self.__class__.__name__
        else:
            self.name = name

        self.handlers = handlers
        self.last_values = {}

        self.configfile = None
        self.load_config(configfile, config)
        # THOUGHTSPOT_CUSTOMIZATION_BEGIN
        self.metric_count = 0
        self.metric_publish_count = 0
        self.class_init_time = time.time()
        self.run_count = 0
        self.log.debug("Initializing collector: %s with collection freq(s):%s",
                      self.name, self.config['interval'])
        # THOUGHTSPOT_CUSTOMIZATION_END

    def load_config(self, configfile=None, override_config=None):
        """
        Process a configfile, or reload if previously given one.
        """

        self.config = configobj.ConfigObj()

        # Load in the collector's defaults
        if self.get_default_config() is not None:
            self.config.merge(self.get_default_config())

        if configfile is not None:
            self.configfile = os.path.abspath(configfile)

        if self.configfile is not None:
            config = load_config(self.configfile)

            if 'collectors' in config:
                if 'default' in config['collectors']:
                    self.config.merge(config['collectors']['default'])

                if self.name in config['collectors']:
                    self.config.merge(config['collectors'][self.name])

        if override_config is not None:
            if 'collectors' in override_config:
                if 'default' in override_config['collectors']:
                    self.config.merge(override_config['collectors']['default'])

                if self.name in override_config['collectors']:
                    self.config.merge(override_config['collectors'][self.name])

        self.process_config()

    def process_config(self):
        """
        Intended to put any code that should be run after any config reload
        event
        """
        if 'byte_unit' in self.config:
            if isinstance(self.config['byte_unit'], str):
                self.config['byte_unit'] = self.config['byte_unit'].split()

        if 'enabled' in self.config:
            self.config['enabled'] = str_to_bool(self.config['enabled'])

        if 'measure_collector_time' in self.config:
            self.config['measure_collector_time'] = str_to_bool(
                self.config['measure_collector_time'])

        # Raise an error if both whitelist and blacklist are specified
        if (self.config.get('metrics_whitelist', None)
                and self.config.get('metrics_blacklist', None)):
            raise DiamondException(
                'Both metrics_whitelist and metrics_blacklist specified ' +
                'in file %s' % configfile)

        # THOUGHTSPOT_CUSTOMIZATION_BEGIN
        # TODO(Pradeep): Move this out so that the whitelist is read just once
        # and not once for every collector
        if self.config.get('whitelist_file', None):
            lines = []
            with open(self.config['whitelist_file']) as f:
                lines = f.read().splitlines()
            self.config['regex'] = []
            start = "[["+self.name+"]]"
            end_regex = "\[\[.*\]\]"
            comment_regex = "#.*"
            started = False
            for line in lines:
                if not line or re.match(comment_regex, line):
                    continue
                if started == False and line == start:
                    started = True
                elif started == True:
                    if re.match(end_regex, line):
                        break
                    else:
                        self.config['regex'].append(line)
        # THOUGHTSPOT_CUSTOMIZATION_END
        if self.config.get('metrics_whitelist', None):
            self.config['metrics_whitelist'] = re.compile(
                self.config['metrics_whitelist'])
        elif self.config.get('metrics_blacklist', None):
            self.config['metrics_blacklist'] = re.compile(
                self.config['metrics_blacklist'])

    def get_default_config_help(self):
        """
        Returns the help text for the configuration options for this collector
        """
        return {
            'enabled': 'Enable collecting these metrics',
            'byte_unit': 'Default numeric output(s)',
            'measure_collector_time': 'Collect the collector run time in ms',
            'metrics_whitelist': 'Regex to match metrics to transmit. ' +
                                 'Mutually exclusive with metrics_blacklist',
            'metrics_blacklist': 'Regex to match metrics to block. ' +
                                 'Mutually exclusive with metrics_whitelist',
        }

    def get_default_config(self):
        """
        Return the default config for the collector
        """
        return {
            # Defaults options for all Collectors

            # Uncomment and set to hardcode a hostname for the collector path
            # Keep in mind, periods are seperators in graphite
            # 'hostname': 'my_custom_hostname',

            # If you perfer to just use a different way of calculating the
            # hostname
            # Uncomment and set this to one of these values:
            # fqdn_short  = Default. Similar to hostname -s
            # fqdn        = hostname output
            # fqdn_rev    = hostname in reverse (com.example.www)
            # uname_short = Similar to uname -n, but only the first part
            # uname_rev   = uname -r in reverse (com.example.www)
            # 'hostname_method': 'fqdn_short',

            # All collectors are disabled by default
            'enabled': False,

            # Path Prefix
            'path_prefix': 'servers',

            # Path Prefix for Virtual Machine metrics
            'instance_prefix': 'instances',

            # Path Suffix
            'path_suffix': '',

            # Default Poll Interval (seconds)
            'interval': 300,

            # Default Event TTL (interval multiplier)
            'ttl_multiplier': 2,

            # Default numeric output
            'byte_unit': 'byte',

            # Collect the collector run time in ms
            'measure_collector_time': False,

            # Whitelist of metrics to let through
            'metrics_whitelist': None,

            # Blacklist of metrics to let through
            'metrics_blacklist': None,
        }

    def get_metric_path(self, name, instance=None):
        """
        Get metric path.
        Instance indicates that this is a metric for a
            virtual machine and should have a different
            root prefix.
        """
        # THOUGHTSPOT_CUSTOMIZATION_BEGIN
        if 'no_prefix_and_suffix' in self.config:
            return name
        # THOUGHTSPOT_CUSTOMIZATION_END
        if 'path' in self.config:
            path = self.config['path']
        else:
            path = self.__class__.__name__

        if instance is not None:
            if 'instance_prefix' in self.config:
                prefix = self.config['instance_prefix']
            else:
                prefix = 'instances'
            if path == '.':
                return '.'.join([prefix, instance, name])
            else:
                return '.'.join([prefix, instance, path, name])

        if 'path_prefix' in self.config:
            prefix = self.config['path_prefix']
        else:
            prefix = 'systems'

        if 'path_suffix' in self.config:
            suffix = self.config['path_suffix']
        else:
            suffix = None

        hostname = get_hostname(self.config)
        if hostname is not None:
            if prefix:
                prefix = ".".join((prefix, hostname))
            else:
                prefix = hostname

        # if there is a suffix, add after the hostname
        if suffix:
            prefix = '.'.join((prefix, suffix))

        if path == '.':
            return '.'.join([prefix, name])
        else:
            return '.'.join([prefix, path, name])

    def get_hostname(self):
        return get_hostname(self.config)

    def collect(self):
        """
        Default collector method
        """
        raise NotImplementedError()

    def publish(self, name, value, raw_value=None, precision=0,
                metric_type='GAUGE', instance=None):
        """
        Publish a metric with the given name
        """
        # THOUGHTSPOT_CUSTOMIZATION_BEGIN
        # Collect monitoring stats for total collected metrics
        self.metric_count += 1
        if self.config.get('whitelist_file', None):
            found = False
            if self.config['regex']:
                for regex in self.config['regex']:
                    if re.search(regex, name, re.IGNORECASE):
                        found = True
                        break
            if not found:
                return
        # THOUGHTSPOT_CUSTOMIZATION_END
        # Check whitelist/blacklist
        if self.config['metrics_whitelist']:
            if not self.config['metrics_whitelist'].match(name):
                return
        elif self.config['metrics_blacklist']:
            if self.config['metrics_blacklist'].match(name):
                return

        # Get metric Path
        path = self.get_metric_path(name, instance=instance)

        # Get metric TTL
        ttl = float(self.config['interval']) * float(
            self.config['ttl_multiplier'])

        # Create Metric
        try:
            metric = Metric(path, value, raw_value=raw_value, timestamp=None,
                            precision=precision, host=self.get_hostname(),
                            metric_type=metric_type, ttl=ttl)
        except DiamondException:
            self.log.error(('Error when creating new Metric: path=%r, '
                            'value=%r'), path, value)
            raise

        # THOUGHTSPOT_CUSTOMIZATION_BEGIN
        # Collect monitoring stats for published metrics
        self.metric_publish_count += 1
        # THOUGHTSPOT_CUSTOMIZATION_END

        # Publish Metric
        self.publish_metric(metric)

    def publish_metric(self, metric):
        """
        Publish a Metric object
        """
        # Process Metric
        for handler in self.handlers:
            handler._process(metric)

    def publish_gauge(self, name, value, precision=0, instance=None):
        return self.publish(name, value, precision=precision,
                            metric_type='GAUGE', instance=instance)

    def publish_counter(self, name, value, precision=0, max_value=0,
                        time_delta=True, interval=None, allow_negative=False,
                        instance=None):
        raw_value = value
        value = self.derivative(name, value, max_value=max_value,
                                time_delta=time_delta, interval=interval,
                                allow_negative=allow_negative,
                                instance=instance)
        return self.publish(name, value, raw_value=raw_value,
                            precision=precision, metric_type='COUNTER',
                            instance=instance)

    def derivative(self, name, new, max_value=0,
                   time_delta=True, interval=None,
                   allow_negative=False, instance=None):
        """
        Calculate the derivative of the metric.
        """
        # Format Metric Path
        path = self.get_metric_path(name, instance=instance)

        if path in self.last_values:
            old = self.last_values[path]
            # Check for rollover
            if new < old:
                old = old - max_value
            # Get Change in X (value)
            derivative_x = new - old

            # If we pass in a interval, use it rather then the configured one
            if interval is None:
                interval = int(self.config['interval'])

            # Get Change in Y (time)
            if time_delta:
                derivative_y = interval
            else:
                derivative_y = 1

            result = float(derivative_x) / float(derivative_y)
            if result < 0 and not allow_negative:
                result = 0
        else:
            result = 0

        # Store Old Value
        self.last_values[path] = new

        # Return result
        return result

    def _run(self):
        """
        Run the collector unless it's already running
        """
        global prefix
        try:
            # THOUGHTSPOT_CUSTOMIZATION_BEGIN
            self.run_count += 1
            self.log.debug("Run number#%s for %s.", self.run_count, self.name)
            self.metric_count = 0
            self.metric_publish_count = 0
            # THOUGHTSPOT_CUSTOMIZATION_END

            start_time = time.time()
            # Collect Data
            self.collect()

            end_time = time.time()
            collector_time = int((end_time - start_time) * 1000)

            self.log.debug('Collection took %s ms', collector_time)

            if 'measure_collector_time' in self.config:
                if self.config['measure_collector_time']:
                    metric_name = 'collector_time_ms'
                    metric_value = collector_time
                    self.publish(prefix + metric_name, metric_value)
                    # THOUGHTSPOT_CUSTOMIZATION_BEGIN
                    # Collect monitoring metrics
                    self.publish_monitoring_metrics()
                    # THOUGHTSPOT_CUSTOMIZATION_END

        finally:
            # After collector run, invoke a flush
            # method on each handler.
            for handler in self.handlers:
                handler._flush()

    # THOUGHTSPOT_CUSTOMIZATION_BEGIN
    def publish_monitoring_metrics(self):
        global prefix
        self.log.debug("Publishing monitoring metrics for: %s", self.name)

        self.publish(prefix + 'collector_run_finished_at',
                     time.time())
        self.publish(prefix + 'collection_frequency_s',
                     int(self.config['interval']))
        self.publish(prefix + 'collector_uptime_ms',
                     (time.time() - self.class_init_time) * 1000)
        # Note:Both metric counts have (+2/+1) to count their own publish count
        # Keep these metrics publish at the end to export their correct values
        self.publish(prefix + 'total_metrics_collected', self.metric_count + 2)
        self.publish(prefix + 'total_metrics_published',
                     self.metric_publish_count + 1)
    # THOUGHTSPOT_CUSTOMIZATION_END

    def find_binary(self, binary):
        """
        Scan and return the first path to a binary that we can find
        """
        if os.path.exists(binary):
            return binary

        # Extract out the filename if we were given a full path
        binary_name = os.path.basename(binary)

        # Gather $PATH
        search_paths = os.environ['PATH'].split(':')

        # Extra paths to scan...
        default_paths = [
            '/usr/bin',
            '/bin'
            '/usr/local/bin',
            '/usr/sbin',
            '/sbin'
            '/usr/local/sbin',
        ]

        for path in default_paths:
            if path not in search_paths:
                search_paths.append(path)

        for path in search_paths:
            if os.path.isdir(path):
                filename = os.path.join(path, binary_name)
                if os.path.exists(filename):
                    return filename

        return binary


class ProcessCollector(Collector):
    """
    Collector with helpers for handling running commands with/without sudo
    """

    def get_default_config_help(self):
        config_help = super(ProcessCollector, self).get_default_config_help()
        config_help.update({
            'use_sudo':     'Use sudo?',
            'sudo_cmd':     'Path to sudo',
        })
        return config_help

    def get_default_config(self):
        """
        Returns the default collector settings
        """
        config = super(ProcessCollector, self).get_default_config()
        config.update({
            'use_sudo':     False,
            'sudo_cmd':     self.find_binary('/usr/bin/sudo'),
        })
        return config

    def run_command(self, args):
        if 'bin' not in self.config:
            raise Exception('config does not have any binary configured')
        if not os.access(self.config['bin'], os.X_OK):
            raise Exception('%s is not executable' % self.config['bin'])
        try:
            command = args
            command.insert(0, self.config['bin'])

            if str_to_bool(self.config['use_sudo']):
                command.insert(0, self.config['sudo_cmd'])

            return subprocess.Popen(command,
                                    stdout=subprocess.PIPE).communicate()
        except OSError:
            self.log.exception("Unable to run %s", command)
            return None
