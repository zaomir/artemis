#!/usr/bin/env python3
"""Trusted host stdin feedback. No recipient address, key or private evidence in git.

An operator first verifies an actual bounce/complaint and its message correlation.
--probe submits only invalid empty JSON; it cannot suppress any subscription.
"""
import argparse
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request,build_opener
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'app'),str(Path(__file__).resolve().parent)]
import funnel_feedback
from capture_fb_enquiry import host_master,NoRedirect

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--apply',action='store_true');mode.add_argument('--probe',action='store_true');args=p.parse_args()
    try:
        raw='{}' if args.probe else sys.stdin.read(2001)
        if len(raw.encode())>2000:raise ValueError('feedback_too_large')
        data=json.loads(raw)
        req=Request('http://127.0.0.1:8082'+funnel_feedback.PATH,data=json.dumps(data).encode(),headers={
            'Content-Type':'application/json','X-Artemis-Feedback-Key':funnel_feedback.intake_key(host_master())})
        try:
            with build_opener(NoRedirect()).open(req,timeout=15) as response:
                result=json.load(response)
                if args.probe:raise RuntimeError('invalid_feedback_accepted')
        except HTTPError as exc:
            if args.probe and exc.code==400:result={'ok':True,'authenticated_invalid_payload_status':400,'subscriptions_changed':0}
            else:raise
        print(json.dumps(result))
    except Exception as exc:
        result={'ok':False,'error_class':type(exc).__name__}
        if isinstance(exc,HTTPError):result['http_status']=exc.code
        print(json.dumps(result));sys.exit(1)
