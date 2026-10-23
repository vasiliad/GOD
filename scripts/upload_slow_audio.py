"""Заливка slower-mp3 (Abraham Shmuelof, CC BY-NC-ND 4.0) на HF-датасет.

Файлы verbatim из slower-EPUB ebible.org (см. build_audio.py); датасет публичный,
некоммерческий, с атрибуцией в карточке. Вызов: python scripts/upload_slow_audio.py
"""
import io, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "arabyan/tanakh-audio"

README = """---
license: cc-by-nc-nd-4.0
language:
- he
tags:
- tanakh
- hebrew-bible
- audio
size_categories:
- 1K<n<10K
---

# Hebrew Bible (Tanakh) audio — read by Abraham Shmuelof (slower take)

Verbatim MP3 redistribution of the slower recording by **Abraham Shmuelof**
(source: ebible.org audio ePubs, https://ebible.org/multimedia/hbo/).

License: **CC BY-NC-ND 4.0** — attribution required, non-commercial use only,
no derivatives. Files are unmodified; only the container/filename changed.
Used by the GOD project (https://vasiliad.github.io/GOD/) — a non-commercial
research simulation; playback is streamed as-is with visible attribution.
"""


def main():
    from huggingface_hub import HfApi
    token = io.open(os.path.join(ROOT, ".agent", "hf_token"), encoding="utf-8").read().strip()
    api = HfApi(token=token)
    who = api.whoami()
    print("аккаунт:", who.get("name"), flush=True)
    api.create_repo(REPO, repo_type="dataset", private=False, exist_ok=True)
    card = os.path.join(ROOT, "data", "slow_mp3", "README.md")
    io.open(card, "w", encoding="utf-8", newline="\n").write(README)
    api.upload_file(path_or_fileobj=card, path_in_repo="README.md", repo_id=REPO, repo_type="dataset")
    print("карточка датасета загружена", flush=True)
    api.upload_folder(
        folder_path=os.path.join(ROOT, "data", "slow_mp3"),
        path_in_repo="slower",
        repo_id=REPO,
        repo_type="dataset",
        commit_message="slower Tanakh audio (Abraham Shmuelof, CC BY-NC-ND 4.0)",
    )
    print("выгрузка завершена:", HF_URL_TEST := "https://huggingface.co/datasets/%s/resolve/main/slower/" % REPO, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
