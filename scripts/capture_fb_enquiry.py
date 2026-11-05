#!/usr/bin/env python3
"""Trusted host interface: stdin private JSON -> fixed internal capture endpoint.

Aside supplies the explicit-request payload, never a key or CRM record. --check
validates without effects; --apply uses the host-only purpose-derived credential.
Do not place contact payloads, messages or credential values in git/task reports.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import funnel_fb


def host_master():
    if os.environ.get('ARTEMIS_ADMIN_TOKEN'):return os.environ['ARTEMIS_ADMIN_TOKEN']
    for line in Path('/etc/artemis/artemis.env').read_text().splitlines():
        match=re.fullmatch(r'(?:export\s+)?ARTEMIS_ADMIN_TOKEN=(.*)',line.strip())
        if match:return match[1].strip().strip('"').strip("'")
    raise RuntimeError('intake_not_configured')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true');mode.add_argument('--apply',action='store_true');mode.add_argument('--probe',action='store_true');args=parser.parse_args()
    try:
        if args.probe:
            data={};event=None
        else:
            raw=sys.stdin.read(16001)
            if len(raw.encode())>16000:raise ValueError('body_too_large')
            data=json.loads(raw);event=funnel_fb.normalize(data)
        if args.check:result={'ok':True,'source_event_id':event['source_event_id'],'side_effects':False}
        else:
            headers={'Content-Type':'application/json','X-Artemis-Intake-Key':funnel_fb.intake_key(host_master())}
            req=Request('http://127.0.0.1:8082'+funnel_fb.PATH,data=json.dumps(data).encode(),headers=headers,method='POST')
            try:
                with build_opener(NoRedirect()).open(req,timeout=15) as response:
                    result=json.load(response)
                    if args.probe:raise RuntimeError('invalid_payload_unexpectedly_accepted')
            except HTTPError as exc:
                if args.probe and exc.code==400:result={'ok':True,'scoped_auth_invalid_payload_status':400,'real_source_submitted':False}
                else:raise
        print(json.dumps(result))
    except Exception as exc:
        result={'ok':False,'error_class':type(exc).__name__}
        if isinstance(exc,HTTPError):result['http_status']=exc.code
        print(json.dumps(result));sys.exit(1)
