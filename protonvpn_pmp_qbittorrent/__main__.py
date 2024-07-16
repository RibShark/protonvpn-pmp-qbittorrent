#! /usr/bin/env python3

import argparse
import logging
import natpmp
import qbittorrentapi
import queue
import sys
import threading
import time
import urllib.parse


class PmpThread(threading.Thread):
    def __init__(self, *, gateway, lifetime, outq):
        super().__init__()
        self.gateway = gateway
        self.lifetime = lifetime
        self.outq = outq

    def run(self):
        prev_port = None
        while True:
            try:
                udp_resp = natpmp.map_udp_port(
                    0, 0, lifetime=self.lifetime, gateway_ip=self.gateway
                )
                tcp_resp = natpmp.map_tcp_port(
                    0, 0, lifetime=self.lifetime, gateway_ip=self.gateway
                )
                if udp_resp.public_port != tcp_resp.public_port:
                    logging.warning(
                        f"Mismatched TCP and UDP ports ({tcp_resp.public_port} != {udp_resp.public_port}"
                    )
                else:
                    if udp_resp.public_port != prev_port:
                        logging.info(f"New public port mapping: {udp_resp.public_port}")
                        prev_port = udp_resp.public_port
                        self.outq.put(udp_resp.public_port)
            except natpmp.NATPMPError:
                logging.exception("NAT-PMP error occurred")
            time.sleep(self.lifetime / 2)


class qBittorrentThread(threading.Thread):
    def __init__(self, *, client, inq):
        super().__init__()
        self.client = client
        self.inq = inq

    def run(self):
        while True:
            public_port = self.inq.get()
            try:
                self.client.app_set_preferences({"listen_port": public_port})
                logging.info(f"qBittorrent peer port set to {public_port}")
            except qbittorrentapi.exceptions.RequestException:
                logging.exception("qBittorrent error occurred")
                self.inq.put(public_port)  # retry
                time.sleep(5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--qbittorrent_url",
        required=True,
        help="URL of the qBittorrent web server, including credentials",
    )
    parser.add_argument(
        "--pmp_gateway", required=True, help="IP address of the NAT-PMP Gateway"
    )
    parser.add_argument(
        "--pmp_lifetime_secs",
        default=60,
        help="Port mapping validity duration to request",
    )
    args = parser.parse_args()

    logging.basicConfig(stream=sys.stderr, level=logging.INFO)

    url = urllib.parse.urlparse(args.qbittorrent_url)
    qbittorrent_client = qbittorrentapi.Client(host=url.geturl(), username=url.username, password=url.password)

    port_mapping_changes = queue.Queue()
    pmp_thread = PmpThread(
        gateway=args.pmp_gateway,
        lifetime=args.pmp_lifetime_secs,
        outq=port_mapping_changes,
    )
    qbittorrent_thread = qBittorrentThread(
        client=qbittorrent_client, inq=port_mapping_changes
    )

    pmp_thread.start()
    qbittorrent_thread.start()

    pmp_thread.join()
    qbittorrent_thread.join()


if __name__ == "__main__":
    main()
