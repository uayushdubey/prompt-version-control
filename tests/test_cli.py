from promptvc.cli.main import build_parser

def test_cli_parser_init():
    parser = build_parser()
    args = parser.parse_args(["init"])
    assert args.command == "init"

def test_cli_parser_commit():
    parser = build_parser()
    args = parser.parse_args(["commit", "summarize", "--prompt", "Summarize this", "--message", "v1"])
    assert args.command == "commit"
    assert args.name == "summarize"
    assert args.prompt == "Summarize this"
    assert args.message == "v1"

def test_cli_parser_run():
    parser = build_parser()
    args = parser.parse_args(["run", "summarize", "v1", "--provider", "openai", "--var", "text=hello"])
    assert args.command == "run"
    assert args.name == "summarize"
    assert args.version == "v1"
    assert args.provider == "openai"
    assert args.var == ["text=hello"]
