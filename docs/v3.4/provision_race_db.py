"""Create the V3.4 race database, empty, if it does not exist yet. Run only by docs/v3.4/run-neo4j-gate.ps1 -Provision.

Refuses unless the name given is exactly the V3.4 race target and the settings name the same target. Creates nothing
else, changes nothing else, drops nothing. Prints the database names before and after (names and states only).
"""
import os
import sys

TARGET = "shipments-v2-world-v34-race-20261016"


def main():
    named = sys.argv[1] if len(sys.argv) > 1 else ""
    if named != TARGET or os.environ.get("SUHAIL_V3_CI_DATABASE") != TARGET:
        sys.exit("refused: only the V3.4 race target may be provisioned")
    import config
    from neo4j import GraphDatabase
    if TARGET.lower() in {str(n).lower() for n in (config.NEO4J_DATABASE, config.SHIPMENT_DATABASE, config.CHAT_DATABASE) if n}:
        sys.exit("refused: the target is configured as an application database")
    driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USERNAME, config.NEO4J_PASSWORD))
    try:
        with driver.session(database="system") as session:
            before = {row["name"]: row["currentStatus"] for row in session.run("SHOW DATABASES YIELD name, currentStatus")}
            if TARGET in before:
                print(f"exists already: {TARGET} ({before[TARGET]}); nothing created")
                return
            session.run(f"CREATE DATABASE `{TARGET}` IF NOT EXISTS WAIT").consume()
            after = {row["name"]: row["currentStatus"] for row in session.run("SHOW DATABASES YIELD name, currentStatus")}
        print(f"created: {TARGET} ({after.get(TARGET)})")
        print("other databases unchanged:", {k: v for k, v in after.items() if k != TARGET} == before)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
