"""UDP authoritative DNS server for svc.test., backed by the snapshot holder.

Each request captures the current Snapshot once and resolves its entire
alias chain against it, so a response never mixes data from two versions.
Publishing never blocks or interrupts serving: the swap is a reference
assignment and old snapshots stay alive for in-flight queries."""

from dnslib import A, CNAME, QTYPE, RCODE, RR
from dnslib.server import BaseResolver, DNSServer

from .zone import NEGATIVE_TTL, ZONE, resolve


class ZoneResolver(BaseResolver):
    def __init__(self, get_snapshot):
        self._get_snapshot = get_snapshot

    def resolve(self, request, handler):
        reply = request.reply()
        qname = str(request.q.qname).lower()
        try:
            qtype = QTYPE[request.q.qtype]
        except KeyError:
            qtype = "UNKNOWN"

        snapshot = self._get_snapshot()  # captured once: single version per answer
        if snapshot is None:
            reply.header.rcode = RCODE.SERVFAIL  # nothing published yet
            return reply

        rcode, answers, negative = resolve(snapshot, qname, qtype)
        reply.header.rcode = getattr(RCODE, rcode)
        if rcode in ("NOERROR", "NXDOMAIN"):
            reply.header.aa = 1
        for name, rtype, value, ttl in answers:
            if rtype == "CNAME":
                rdata = CNAME(value)
            elif rtype == "SOA":
                rdata = value
            else:
                rdata = A(value)
            reply.add_answer(
                RR(rname=name, rtype=getattr(QTYPE, rtype), rclass=1, ttl=ttl, rdata=rdata)
            )
        if negative:
            # Both NXDOMAIN and NODATA carry the apex SOA so resolvers can
            # negatively cache this answer, and know the enclosing zone exists.
            # Taken from the same snapshot as the answer decisions above.
            reply.add_auth(
                RR(rname=ZONE, rtype=QTYPE.SOA, rclass=1, ttl=NEGATIVE_TTL,
                   rdata=snapshot.soa())
            )
        return reply


def start_dns_server(get_snapshot, host, port):
    server = DNSServer(ZoneResolver(get_snapshot), port=port, address=host, tcp=False)
    server.start_thread()  # dnslib marks the thread as daemon
    return server
