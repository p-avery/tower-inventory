#!/usr/bin/env python
#
# When using with tower:
# . /var/lib/awx/venv/ansible/bin/activate
# pip install networkx
#

"""
Ansible Tower dynamic inventory from inventory script
==========================================

Generates dynamic inventory for Tower from a group in
an exsiting Tower inventory.

Supply TOWER_INVENTORY: # and TOWER_INVENTORY_GROUP: '' as
environment variables on custom script source with Tower credential

Author: Will Tome (@willtome)
"""

import json
import os
import networkx as nx
import re
import requests
from requests.auth import HTTPBasicAuth
from urlparse import urljoin

def parse_configuration():

    host_name = os.environ.get("TOWER_HOST", None)
    username = os.environ.get("TOWER_USERNAME", None)
    password = os.environ.get("TOWER_PASSWORD", None)
    ignore_ssl = os.environ.get("TOWER_IGNORE_SSL", "1").lower() in ("1", "yes", "true")
    inventory = os.environ.get("TOWER_INVENTORY", None)
    license_type = os.environ.get("TOWER_LICENSE_TYPE", "enterprise")
    inventory_group = os.environ.get("TOWER_INVENTORY_GROUP", "all")

    errors = []
    if not host_name:
        errors.append("Missing TOWER_HOST in environment")
    if not username:
        errors.append("Missing TOWER_USERNAME in environment")
    if not password:
        errors.append("Missing TOWER_PASSWORD in environment")
    if not inventory:
        errors.append("Missing TOWER_INVENTORY in environment")
    if not inventory_group:
        errors.append("Missing TOWER_INVENTORY_GROUP in environment")
    if errors:
        raise RuntimeError("\n".join(errors))

    return dict(tower_host=host_name,
                tower_user=username,
                tower_pass=password,
                tower_inventory=inventory,
                tower_license_type=license_type,
                ignore_ssl=ignore_ssl,
                inventory_group=inventory_group)

def read_tower_inventory(tower_host, tower_user, tower_pass, inventory, license_type, ignore_ssl=False):
    if not re.match('(?:http|https)://', tower_host):
        tower_host = "https://{}".format(tower_host)
    inventory_url = urljoin(tower_host, "/api/v2/inventories/{}/script/?hostvars=1&towervars=1&all=1".format(inventory.replace('/', '')))
    config_url = urljoin(tower_host, "/api/v2/config/")
    try:
        if license_type != "open":
            config_response = requests.get(config_url,
                                           auth=HTTPBasicAuth(tower_user, tower_pass),
                                           verify=not ignore_ssl)
            if config_response.ok:
                source_type = config_response.json()['license_info']['license_type']
                if not source_type == license_type:
                    raise RuntimeError("Tower server licenses must match: source: {} local: {}".format(source_type,
                                                                                                       license_type))
            else:
                raise RuntimeError("Failed to validate the license of the remote Tower: {}".format(config_response.data))

        response = requests.get(inventory_url,
                                auth=HTTPBasicAuth(tower_user, tower_pass),
                                verify=not ignore_ssl)
        if response.ok:
            return response.json()
        json_reason = response.json()
        reason = json_reason.get('detail', 'Retrieving Tower Inventory Failed')
    except requests.ConnectionError, e:
        reason = "Connection to remote host failed: {}".format(e)
    except json.JSONDecodeError, e:
        reason = "Failed to parse json from host: {}".format(e)
    raise RuntimeError(reason)

def load_data():
    raw_data=open('aws.json').read()
    json_data=json.loads(raw_data)
    return json_data

def graph_inventory(json_data):
    graph = nx.DiGraph()
    for group in json_data.keys():
        if group != '_meta':
            graph.add_node(group, type='group')
            for child in json_data[group]['children']:
                graph.add_node(child, type='group')
                graph.add_edge(group,child)
            for host in json_data[group]['hosts']:
                graph.add_node(host, type='host')
                graph.add_edge(group, host)
    return graph

def find_hosts(graph, group):
    tree = nx.DiGraph(list(nx.dfs_edges(graph,group)))
    leafs = [x for x in tree.nodes() if graph.node[x]['type'] == 'host' ]
    return leafs

def find_groups(graph,hosts):
    reverse = graph.reverse()
    groups = []
    for h in hosts:
        host_graph = nx.DiGraph(list(nx.bfs_edges(reverse,h)))
        host_groups = [x for x in host_graph.nodes() if graph.node[x]['type'] == 'group' ]
        groups = groups + list(set(host_groups) - set(groups))
    return groups

def build_inventory(json_data, hosts, groups):
    new_inventory = {'_meta': {'hostvars':{}}}
    for group in groups:
        og_group = json_data[group]
        new_inventory[group] = {
            'hosts': list(set(og_group['hosts']).intersection(hosts)),
            'groups': list(set(og_group['children']).intersection(groups)),
            'vars': og_group['vars']}

    for host in hosts:
        new_inventory['_meta']['hostvars'][host] = json_data['_meta']['hostvars'][host]

    return new_inventory

def main():
    #json_data=load_data()
    config = parse_configuration()
    json_data = read_tower_inventory(config['tower_host'],
                                           config['tower_user'],
                                           config['tower_pass'],
                                           config['tower_inventory'],
                                           config['tower_license_type'],
                                           ignore_ssl=config['ignore_ssl'])
    if config['inventory_group'] in json_data.keys():
        graph=graph_inventory(json_data)
        hosts=find_hosts(graph, config['inventory_group'])
        groups=find_groups(graph,hosts)
        new_inventory = build_inventory(json_data, hosts, groups)
    else:
        new_inventory={}

    print(json.dumps(new_inventory))

if __name__ == '__main__':
    main()
