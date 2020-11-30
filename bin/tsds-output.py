#!/usr/bin/python3

import sys
import json, yaml
import requests

print("args are %s " % sys.argv)

if len(sys.argv) < 2:
    print("Usage: %s <config file>" % sys.argv[0])
    sys.exit(1)

config_file = sys.argv[1]

def main():    

    config          = TSDSConfig(config_file)
    datatransformer = DataTransformer(config)

    block = []

    for line in sys.stdin:
        #print("I got a line %s" % line)

        # Example line:
        # {"fields":{"ifAdminStatus":1,"ifInDiscards":0,"ifInErrors":0,"ifInNUcastPkts":0,"ifInOctets":0,"ifInUcastPkts":0,"ifInUnknownProtos":0,"ifLastChange":898273758,"ifMtu":2147483647,"ifOperStatus":1,"ifOutDiscards":0,"ifOutErrors":0,"ifOutNUcastPkts":0,"ifOutOctets":0,"ifOutQLen":0,"ifOutUcastPkts":0,"ifPhysAddress":"3c:61:04:07:bb:c0","ifSpecific":".0.0","ifSpeed":4294967295,"ifType":161},"name":"interface","tags":{"agent_host":"rtr.ipiu.ilight.net","host":"io3.bldc.grnoc.iu.edu","ifDescr":"ae0.32767","ifIndex":"518","ifName":"ae0.32767"},"timestamp":1606510153}

        try:
            data = json.loads(line)
        except:
            print("Unable to parse line = \"%s\", skipping" % line)
            continue

        # rename everything, apply counters, etc. Returns a fully
        # formed TSDS update message
        datatransformer.update(data, block)

        if len(block) >= 10:
            _send_data(config, block)
            block = []


def _send_data(config, data):
    json_data  = json.dumps(data)
    tsds_creds = config.credentials()
    result     = requests.post(tsds_creds['url'] + "/services/push.cgi", 
                               data = {"method": "add_data", "data": json_data}, 
                               auth = (tsds_creds['username'], tsds_creds['password']))

    # TODO: error handling here, at least log it
    print(result.text)


# Some helper classes

class TSDSConfig(object):
    def __init__(self, config_file):
        # TODO: some sort of sanity checking here
        with open(config_file) as f:
            self.config = yaml.load(f)
        
    def types(self):
        return [x['telegraf_name'] for x in self.config['data']]

    def credentials(self):
        return self.config['credentials']

    def data_config(self, telegraf_name):
        for data_type in self.config['data']:
            if data_type['telegraf_name'] == telegraf_name:
                return data_type
        return None

class DataTransformer(object):
    # More than meets the eye
    def __init__(self, config):
        self.config = config
        self.cache  = {}

    def update(self, data, block):
        name      = data['name']
        fields    = data['fields']
        tags      = data['tags']
        timestamp = data['timestamp']

        data_config = self.config.data_config(name)

        # Some data type we don't know about, skip it
        # Possibly a misconfig
        if not data_config:
            print("Ignoring unknown data type = %s" % name)
            return None

        interval = data_config['interval']

        # Pull out the metadata from the "tags" element
        # This effectively renames + pulls out the value
        metadata = {}
        for config in data_config['metadata']:
            metadata[config['to']] = tags[config['from']]


        # Now we have our metadata structures all renamed, 
        # grab our local cache so we can process values
        # and convert to rates if needed

        # initialize this measurement type cache if needed
        meas_cache = self.cache.setdefault(name, {})
        cache_key  = "".join(sorted(metadata.values()))
        cache      = meas_cache.setdefault(cache_key, {})


        # And now the data fields, same deal except from the "fields"
        data_fields = {}
        for config in data_config['fields']:
            value = fields[config['from']]

            if config.get('rate'):
                value = self._calculate_rate(cache, config['to'], timestamp, value, interval)

            data_fields[config['to']] = value


        tsds_data_name = data_config["tsds_name"]

        tsds_data = {
            "meta": metadata,
            "time": timestamp,
            "values": data_fields,
            "interval": interval,
            "type": tsds_data_name
        }
        #print(tsds_data)

        block.append(tsds_data)

        # if we have any additional metadata fields, we'll process them as a separate message        
        if "optional_metadata" in data_config:

            # These fields aren't always there, so we have to make sure first
            has_any = False            

            for opt_config in data_config["optional_metadata"]:
                opt_to   = opt_config['to']
                opt_from = opt_config['from']

                if opt_from in tags:
                    metadata[opt_to] = tags[opt_from]
                    has_any = True

            if has_any:
                metadata_data = {
                    "meta": metadata,
                    "time": timestamp,
                    "type": tsds_data_name + ".metadata"
                }

                block.append(metadata_data)


    def _calculate_rate(self, cache, value_name, timestamp, value, interval):

        if value is None:
            return None

        (last_timestamp, last_value) = cache.setdefault(value_name, (timestamp, None))
        cache[value_name] = (timestamp, value)

        # If we didn't have any prior entries, can't calculate
        if last_value is None:
            return None

        delta = timestamp - last_timestamp;

        # If we DID have a prior entry, we can maybe calc the rate

        # Some rough sanity, don't count values that are really old
        if (delta > 6 * interval):
            return None

        delta_value = value - last_value;


        # Handle overflow / reset here, counters shouldn't go down normally
        if value < last_value:
            if value > 2**32:
                delta_value = 2**64 - last_value + value;            
            else:
                delta_value = 2**32 - last_value + value;
        
        rate = delta_value / delta;
        
        return rate;
        

main()
