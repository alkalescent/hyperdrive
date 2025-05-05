import os
from dotenv import load_dotenv, find_dotenv
from github import Github, Auth

load_dotenv(find_dotenv('config.env'))

token = os.environ.get('GITHUB')
repo_name = os.environ.get('GITHUB_REPOSITORY')
auth = Auth.Token(token)
git = Github(auth=auth)
repo = git.get_repo(repo_name)
workflows = repo.get_workflows()
for workflow in workflows:
    try:
        workflow.enable()
    except Exception as e:
        print(e)
git.close()
