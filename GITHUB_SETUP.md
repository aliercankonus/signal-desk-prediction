# GitHub setup

The package can be pushed to an existing GitHub repository.

## Option A — from your machine

```bash
cd signal-desk-prediction-v16
git init
git add .
git commit -m "Add signal desk prediction v16 skeleton"
git branch -M main
git remote add origin git@github.com:<owner>/<repo>.git
git push -u origin main
```

## Option B — ChatGPT connector

The available GitHub connector can create/update files in an existing repository, but it needs the repository full name, for example:

```text
owner/repo
```

It cannot infer where to push without that repository name.
