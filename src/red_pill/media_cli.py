"""media_cli — CLI `red-pill media` (docs/CORE/MEDIA_MODELS.md): router, staging y promoción."""

from __future__ import annotations

import argparse
import json

from red_pill.core import media_staging
from red_pill.core.media_router import get_media_profiles


def _fail(msg: str) -> "argparse.Namespace":
	print(f"[media] {msg}")
	raise SystemExit(1)


def handle_media(args: argparse.Namespace) -> None:
	cmd = getattr(args, "media_cmd", None)

	if cmd == "resolve":
		try:
			print(get_media_profiles().resolve(task=args.task, model=args.model))
		except Exception as e:  # noqa: BLE001
			_fail(str(e))

	elif cmd == "validate":
		req = {}
		if args.task:
			req["task"] = args.task
		if args.model:
			req["model"] = args.model
		if args.width:
			req["width"] = args.width
		if args.height:
			req["height"] = args.height
		print(json.dumps(get_media_profiles().validate(req), ensure_ascii=False, indent=2))

	elif cmd == "adapt":
		params = {}
		if args.width:
			params["width"] = args.width
		if args.height:
			params["height"] = args.height
		try:
			adapted, warnings = get_media_profiles().adapt(args.model, params)
		except Exception as e:  # noqa: BLE001
			_fail(str(e))
		else:
			print(json.dumps({"model": args.model, "adapted": adapted, "warnings": warnings}, ensure_ascii=False, indent=2))

	elif cmd == "staging":
		path = media_staging.order_dir(args.title, create=True) if args.title else media_staging.staging_root()
		print(path)

	elif cmd == "promote":
		try:
			print(media_staging.promote(args.title, args.to, name=args.name, move=args.move))
		except Exception as e:  # noqa: BLE001
			_fail(str(e))

	else:
		print("uso: red-pill media {resolve|validate|adapt|staging|promote}")
		raise SystemExit(2)
