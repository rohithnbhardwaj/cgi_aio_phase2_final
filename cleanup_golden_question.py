from __future__ import annotations

import argparse
from backend.feedback_store import cleanup_question_goldens

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", required=True)
    ap.add_argument("--sql", default="")
    args = ap.parse_args()
    res = cleanup_question_goldens(args.question, preferred_sql=(args.sql or None))
    print(res)

if __name__ == "__main__":
    main()
