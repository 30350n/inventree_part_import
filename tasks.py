import sys
import time

from invoke import task
import requests
from requests.auth import HTTPBasicAuth

# this file is a minimal version of
# https://github.com/inventree/inventree-python/blob/master/tasks.py

DOCKER_COMPOSE_CMD = "docker compose -f tests/docker-compose.yaml"
DOCKER_RUN_CMD = f"{DOCKER_COMPOSE_CMD} run inventree-part-import-test"

HOST = "http://localhost:55555"
USERNAME = "testuser"
PASSWORD = "testpassword"

@task
def reset_data(c, debug=False):
    print("resetting database ...", end=" ")
    hide = None if debug else "both"
    c.run(f"{DOCKER_RUN_CMD} invoke delete-data -f", hide=hide)
    c.run(f"{DOCKER_RUN_CMD} invoke migrate", hide=hide)
    c.run(f"{DOCKER_RUN_CMD} invoke import-fixtures", hide=hide)
    print("done.")

@task(post=[reset_data])
def update_image(c, debug=True):
    print("updating image ...", end=" ")
    hide = None if debug else "both"
    c.run(f"{DOCKER_COMPOSE_CMD} pull", hide=hide)
    c.run(f"{DOCKER_RUN_CMD} invoke update", hide=hide)
    print("done.")

@task
def check_server(c, host=HOST, username=USERNAME, password=PASSWORD, debug=True):
    auth = HTTPBasicAuth(username=username, password=password)
    url = f"{host}/api/user/token/"

    try:
        response = requests.get(url, auth=auth, timeout=0.5)
    except Exception as e:
        if debug:
            print(f"error: {e}")
        return False

    if response is None:
        return False

    if response.status_code != 200:
        if debug:
            print(f"error: invalid status code '{response.status_code}'")
        return False

    if "token" not in response.text:
        if debug:
            print(f"error: no token in response '{response.text}'")
        return False

    return True

@task
def start_server(c, debug=False):
    print("starting server ...", end=" ")
    c.run(f"{DOCKER_COMPOSE_CMD} up -d", hide=None if debug else "both")

    for _ in range(60):
        if check_server(c, debug=False):
            print("done.")
            break
        time.sleep(1)
    else:
        print("failed to get response.")
        sys.exit(1)

@task
def stop_server(c, debug=False):
    print("stopping server ...", end=" ")
    c.run('docker-compose -f test/docker-compose.yml down', hide=None if debug else 'both')
    print("done.")

@task
def test(c, target=None, update=False, reset=False, debug=False):
    if update:
        update_image(c, debug=debug)

    if reset:
        stop_server(c, debug=debug)
        reset_data(c, debug=debug)

    start_server(c)

    print("running tests ...", end=" ")
    if target:
        c.run(f"pytest {target}")
    else:
        c.run("pytest")
    print("done.")
