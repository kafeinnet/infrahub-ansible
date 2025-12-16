# Copyright (c) 2023 Opsmill
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
"""
A lookup function designed to return formatted nodes from the Infrahub API
"""

from __future__ import absolute_import, annotations, division, print_function

__metaclass__ = type

DOCUMENTATION = """
---
name: nodes
author:
    - Fabien Dupont <fabien.dupont@eurofiber.com>
short_description: Queries and returns nodes from Infrahub by kind, name, id or hfid
description:
    - Queries and returns nodes from Infrahub by kind, name, id or hfid
options:
    api_endpoint:
        description: Endpoint of the Infrahub API
        required: True
        env:
          - name: INFRAHUB_ADDRESS
    token:
        required: True
        description:
          - Infrahub API token to be able to read against Infrahub.
        env:
          - name: INFRAHUB_API_TOKEN
    timeout:
        required: False
        description: Timeout for Infrahub requests in seconds
        type: int
        default: 10
    kind:
        required: True
        description:
          - Type of object to retrieve from Infrahub database
        type: str
    name:
        required: False
        description:
          - If set, only the node having this name (`name__value=...`) will be returned
        type: str
    id:
        required: False
        description:
          - If set, only the node having this ID will be returned
        type: str
    hfid:
        required: False
        description:
          - If set, only the node having this Human Friendly ID will be returned
        type: str
    branch:
        required: False
        description:
          - Branch in which the request is made
        type: str
        default: main
    validate_certs:
        description:
          - Whether or not to validate SSL of the Infrahub instance
        required: False
        default: True
"""

EXAMPLES = """
- name: Infrahub lookup
  gather_facts: false
  hosts: localhost

  tasks:
    - name: Get Non-existing kind
      ansible.builtin.debug:
        msg: "Found {{ query('opsmill.infrahub.nodes', kind='TrombonneACoulisse') | length }} node(s)"

    - name: Get multiple nodes
      ansible.builtin.debug:
        msg: "Found {{ query('opsmill.infrahub.nodes', kind='VirtualizationVirtualMachine') | length }} node(s)"

    - name: Get one node by name
      ansible.builtin.debug:
        msg: "Found node {{ (query('opsmill.infrahub.nodes', kind='VirtualizationVirtualMachine', name='vm001') | first).name }}"

    - name: Display a node attributes
      ansible.builtin.debug:
        msg: "{{ query('opsmill.infrahub.nodes', kind='VirtualizationVirtualMachine', hfid=['vm002']) | first }}"
"""

RETURN = """
  data:
    description:
      - Found nodes with formatted attributes
    type: list
"""

import os
from typing import Any

from ansible.errors import AnsibleError, AnsibleLookupError
from ansible.plugins.lookup import LookupBase
from ansible.utils.display import Display
from ansible_collections.opsmill.infrahub.plugins.module_utils.infrahub_utils import (
    HAS_INFRAHUBCLIENT,
    InfrahubclientWrapper,
)


def _format_node_attributes(node: dict | str | bool | int | None) -> dict | str | bool | int | None:
    """Format node attributes recurively.

    Args:
        node: An unformatted node

    Returns:
        A node with his attributes formatted
    """
    if not isinstance(node, dict):
        return node

    if "value" in node:
        # A single value
        return _format_node_attributes(node.get("value"))

    if "node" in node:
        # A reference to another node
        return _format_node_attributes(node.get("node"))

    if "edges" in node:
        # A list of results
        return [_format_node_attributes(n) for n in node.get("edges")]

    return {k: _format_node_attributes(v) for k, v in node.items()}


class LookupModule(LookupBase):
    """
    LookupModule(LookupBase) is defined by Ansible

    Parameters:
        LookupBase (LookupBase): Ansible Lookup Plugin
    """

    def run(
        self,
        terms: str,  # noqa: ARG002
        variables: Any | None = None,  # noqa: ARG002
        **kwargs: dict[str, Any],
    ):
        """Runs Ansible Lookup Plugin for using Infrahub GraphQL endpoint

        Raises:
            AnsibleLookupError: Error in data loaded into the plugin
            AnsibleError: Generic Ansible Error

        Returns:
            dict: Data returned from Infrahub endpoint
        """
        if not HAS_INFRAHUBCLIENT:
            raise (AnsibleError("infrahub_sdk must be installed to use this plugin"))

        api_endpoint = kwargs.get("api_endpoint") or os.getenv("INFRAHUB_ADDRESS")
        token = kwargs.get("token") or os.getenv("INFRAHUB_API_TOKEN")
        if api_endpoint is None:
            raise AnsibleLookupError("Missing Infrahub API Endpoint ")
        if token is None:
            raise AnsibleLookupError("Missing Infrahub TOKEN")

        api_endpoint = api_endpoint.strip("/")

        validate_certs = kwargs.get("validate_certs", True)
        if not isinstance(validate_certs, bool):
            raise AnsibleLookupError("validate_certs must be a boolean")

        timeout = kwargs.get("timeout", 10)
        branch = kwargs.get("branch", "main")

        kind = kwargs.get("kind")
        if kind is None:
            raise AnsibleLookupError("kind parameter was not passed")

        node_name = kwargs.get("name")
        if node_name is not None and not isinstance(node_name, str):
            raise AnsibleLookupError("name must be a str")

        node_id = kwargs.get("id")
        if node_id is not None and not isinstance(node_id, str):
            raise AnsibleLookupError("id must be a str")

        node_hfid = kwargs.get("hfid")
        if node_hfid is not None:
            if not isinstance(node_hfid, list):
                raise AnsibleLookupError("hfid must be a list of str")
            for item in node_hfid:
                if not isinstance(item, str):
                    raise AnsibleLookupError("hfid must be a list of str")

        if len(list(filter(lambda v: v is not None, [node_name, node_id, node_hfid]))) > 1:
            raise AnsibleLookupError("name, id and hfid are mutually exclusive")

        results = []
        try:
            Display().v("Initializing Infrahub Client")
            client = InfrahubclientWrapper(
                api_endpoint=api_endpoint,
                token=token,
                branch=branch,
                timeout=timeout,
                validate_certs=validate_certs,
                display=Display(),
            )

            results = []
            if node_id is not None:
                results = [client.fetch_single_node(kind=kind, branch=branch, id=node_id)]
            elif node_hfid is not None:
                results = [client.fetch_single_node(kind=kind, branch=branch, hfid=node_hfid)]
            elif node_name is not None:
                results = client.fetch_nodes(kind=kind, branch=branch, filters={"name__value": node_name})
            else:
                results = client.fetch_nodes(kind=kind, branch=branch)

            results = [n.get_raw_graphql_data() for n in results or []]

        except Exception as exc:
            raise AnsibleError(str(exc)) from exc

        return [_format_node_attributes(n) for n in results]
