from scripts.run_promotion_hunter_pilot import mask_destination, parser


def test_script_defaults_to_analysis_only_once():
    args = parser().parse_args(["--term", "ssd"])
    assert args.mode == "analysis-only"
    assert args.once and not args.schedule
    assert args.limit == 5


def test_script_supports_dry_run_and_masks_destination():
    args = parser().parse_args(["--mode", "dry-run", "--term", "ssd"])
    assert args.mode == "dry-run"
    assert mask_destination("5511999999999") == "***9999"
