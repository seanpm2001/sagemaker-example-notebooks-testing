import os
import subprocess

import boto3
from botocore.exceptions import ClientError

import common

OAUTH_SECRET_ID = "/codebuild/github/oauth"
logger = common.get_logger()
cp_client = boto3.client("codepipeline")

GIT_RPM = "git-2.13.5-1.53.amzn1.x86_64.rpm"
GIT_PATH = "/tmp/usr/bin/git"
GIT_ENV = {
    "HOME": "/var/task",
    "GIT_TEMPLATE_DIR": "/tmp/usr/share/git-core/templates",
    "GIT_EXEC_PATH": "/tmp/usr/libexec/git-core",
}


def install_git():
    logger.warning("installing git")

    git_rpm_url = (
        f'http://packages.{os.environ["AWS_REGION"]}.amazonaws.com'
        "/2017.03/updates/ba2b87ec77c7/x86_64/Packages"
        f"/{GIT_RPM}"
    )

    # download
    subprocess.check_call(f"curl -s -o /tmp/{GIT_RPM} {git_rpm_url}".split())

    # check signature
    subprocess.check_call(f"rpm -K /tmp/{GIT_RPM}".split())

    # install
    subprocess.check_call(f"rpm2cpio {GIT_RPM} | cpio -id", shell=True, cwd="/tmp")

    # remove rpm file
    os.remove(f"/tmp/{GIT_RPM}")


def get_oauth_token():
    secrets_client = boto3.client("secretsmanager")
    return secrets_client.get_secret_value(SecretId=OAUTH_SECRET_ID)["SecretString"]


def start_pipeline(name):
    try:
        resp = cp_client.start_pipeline_execution(name=name)
        execution_id = resp["pipelineExecutionId"]
        logger.info("started pipeline %s - execution id %s", name, execution_id)
    except ClientError:
        # TODO trigger cloudwatch alarm?
        logger.exception("failed to start pipeline")


def changes_since_last_release(source):
    # shallow clone repo with depth = 1, then look for a release tag
    # if we find a tag, that means no commits since last release
    shallow_clone(source)
    return has_real_commits(source)


def has_real_commits(source):
    cmd = [GIT_PATH, "log", "--pretty=%s"]

    p = subprocess.Popen(
        cmd,
        cwd=f'/tmp/{source["repo"]}',
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        env=GIT_ENV,
    )

    out, err = p.communicate()
    if p.returncode != 0:
        raise ValueError(f"git log error: {err}")

    logger.info("most recent commit: %s", out)

    # if most recent commit was generated by the gitrelease.py process,
    # then there are no real changes
    return not out.startswith("update development version to v")


def shallow_clone(source):
    subprocess.check_call(f'rm -fr /tmp/{source["repo"]}'.split())

    oauth_token = get_oauth_token()
    uri = f'https://{oauth_token}@github.com/{source["owner"]}/{source["repo"]}.git'
    cmd = f'{GIT_PATH} clone --depth 1 --single-branch --branch {source["branch"]} {uri}'.split()
    p = subprocess.Popen(
        cmd,
        cwd="/tmp",
        env=GIT_ENV,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _, err = p.communicate()

    if p.returncode != 0:
        raise ValueError(f"git clone error: {err}")


def handler(event, context):  # pylint: disable=unused-argument
    logger.info(event)

    pipeline_name = event["pipelineName"]

    start_pipeline(pipeline_name)


# initialize git
install_git()
