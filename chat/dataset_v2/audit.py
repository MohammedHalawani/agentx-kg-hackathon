"""Read-only local graph census, recovery snapshot and representative path inspection."""
import argparse
from collections import Counter
from pathlib import Path

from dataset_v2.contracts import canonical, digest_records
from dataset_v2.load import DEFAULT_DATABASE, read_bundle, target_guard


def json_value(value):
    if isinstance(value,dict):return {key:json_value(item) for key,item in value.items()}
    if isinstance(value,(list,tuple)):return [json_value(item) for item in value]
    if hasattr(value,"to_native") or hasattr(value,"isoformat"):
        return {"temporal_type":type(value).__name__,"value":str(value)}
    return value


def snapshot(driver,database: str,destination: Path) -> dict:
    if destination.exists():raise ValueError("Choose a new read-only snapshot destination")
    def read(tx):
        nodes=[json_value(dict(row)) for row in tx.run(
            "MATCH (n) RETURN elementId(n) AS id,labels(n) AS labels,properties(n) AS properties")]
        edges=[json_value(dict(row)) for row in tx.run(
            "MATCH (a)-[r]->(b) RETURN elementId(r) AS id,elementId(a) AS start,elementId(b) AS end,"
            "type(r) AS kind,properties(r) AS properties")]
        indexes=[json_value(dict(row)) for row in tx.run(
            "SHOW INDEXES YIELD name,type,state,labelsOrTypes,properties RETURN name,type,state,labelsOrTypes,properties ORDER BY name")]
        return sorted(nodes,key=lambda row:row["id"]),sorted(edges,key=lambda row:row["id"]),indexes
    with driver.session(database=database,default_access_mode="READ") as session:
        nodes,edges,indexes=session.execute_read(read)
    report={"database":database,"read_only":True,"nodes":len(nodes),"edges":len(edges),
            "labels":dict(Counter(label for row in nodes for label in row["labels"])),
            "relationship_types":dict(Counter(row["kind"] for row in edges)),"indexes":indexes,
            "hashes":{"nodes":digest_records(nodes),"edges":digest_records(edges)}}
    destination.mkdir(parents=True)
    for name,rows in (("nodes",nodes),("edges",edges)):
        with (destination/f"{name}.jsonl").open("w",encoding="utf-8",newline="\n") as stream:
            for row in rows:stream.write(canonical(row)+"\n")
    (destination/"census.json").write_text(canonical(report)+"\n",encoding="utf-8")
    return report


def inspect_shadow(driver,bundle,destination: Path) -> dict:
    if destination.exists():raise ValueError("Choose a new inspection report file")
    choices=(("healthy_history","on_time","history"),("resolved_barcode","different_barcode","history"),
             ("disputed_delivery","report_with_corroboration","development"),
             ("possible_misdelivery","report_different_location","development"),
             ("session_gap","absent_session_receipt","development"),
             ("traffic_safe_return","traffic_safe_return","development"),
             ("partial_packages","partial_packages","held_out"),
             ("independent_custody_reports","conflicting_custody_sources","development"),
             ("reopened","report_after_prior_outcome","development"),
             ("bulky_organization","bulky_normal","history"))
    report={"database":DEFAULT_DATABASE,"read_only":True,"representatives":[]}
    with driver.session(database=DEFAULT_DATABASE,default_access_mode="READ") as session:
        report["counts"]=dict(session.run("MATCH (n:V2Entity) RETURN count(n) AS entities").single())
        report["relationship_count"]=session.run("MATCH ()-[r]->() RETURN count(r) AS edges").single()["edges"]
        report["marker"]=dict(session.run("MATCH (m:_V2Import) RETURN m.state AS state,m.manifest_hash AS manifest_hash").single())
        report["indexes"]=[dict(row) for row in session.run("SHOW INDEXES YIELD name,type,state RETURN name,type,state ORDER BY name")]
        for name,recipe,split in choices:
            gold=next(row for row in bundle.world.gold.values() if row["recipe_id"]==recipe and row["split"]==split)
            sid=gold["shipment_id"]
            custody=[json_value(dict(row)) for row in session.run(
                "MATCH (s:Shipment {entity_id:$sid})-[:HAS_PACKAGE]->(p:Package)-[:HAS_CUSTODY_EVENT]->(c:CustodyEvent) "
                "OPTIONAL MATCH (c)-[:OBSERVED_BY]->(raw:ScanEvent) "
                "OPTIONAL MATCH (a:VehicleAssignment {entity_id:c.assignment_id})-[:ASSIGNED_DRIVER]->(d:Driver) "
                "RETURN p.entity_id AS package,c.entity_id AS event,c.event_type AS type,c.occurred_at AS time,"
                "c.from_id AS from_id,c.to_id AS to_id,c.source_quality AS source_quality,raw.entity_id AS source,"
                "a.entity_id AS assignment,d.entity_id AS driver ORDER BY time,event",sid=sid)]
            lifecycle=[json_value(dict(row)) for row in session.run(
                "MATCH (c:Case {holdout_group:$sid}) OPTIONAL MATCH (c)-[:RESOLVED_BY]->(r:Resolution)-[:HAS_OUTCOME]->(o:Outcome) "
                "RETURN c.state AS state,r.entity_id AS resolution,o.entity_id AS outcome,o.success AS success,"
                "o.verification_status AS verification_status,o.invalidated AS invalidated",sid=sid)]
            topology=[json_value(dict(row)) for row in session.run(
                "MATCH (s:Shipment {entity_id:$sid})-[:HAS_PLAN]->(j:ExpectedJourney)-[:EXPECTS]->(m:ExpectedMilestone) "
                "RETURN j.entity_id AS plan,count(m) AS expected_milestones",sid=sid)]
            telemetry=[json_value(dict(row)) for row in session.run(
                "MATCH (g:GPSObservation {holdout_group:$sid}) RETURN g.vehicle_id AS vehicle,g.position_scope AS scope,count(g) AS observations",sid=sid)]
            report["representatives"].append({"name":name,"shipment_id":sid,"split":split,
                "custody":custody,"lifecycle":lifecycle,"expected":topology,"telemetry":telemetry,
                "initial_supported_codes":gold["assessment"]["supported_codes"]})
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(canonical(report)+"\n",encoding="utf-8")
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-v1",type=Path)
    parser.add_argument("--bundle",type=Path)
    parser.add_argument("--inspect-output",type=Path)
    args=parser.parse_args(argv)
    if bool(args.snapshot_v1)==bool(args.bundle):parser.error("Choose V1 snapshot or shadow inspection")
    if args.bundle and not args.inspect_output:parser.error("Inspection requires --inspect-output")
    import config
    from neo4j import GraphDatabase
    target_guard(config.NEO4J_URI,DEFAULT_DATABASE,(config.SHIPMENT_DATABASE,config.NEO4J_DATABASE,config.CHAT_DATABASE))
    with GraphDatabase.driver(config.NEO4J_URI,auth=(config.NEO4J_USERNAME,config.NEO4J_PASSWORD)) as driver:
        if args.snapshot_v1:
            report=snapshot(driver,config.SHIPMENT_DATABASE,args.snapshot_v1)
            print(canonical(report))
        else:
            report=inspect_shadow(driver,read_bundle(args.bundle),args.inspect_output)
            print(canonical({"database":report["database"],"counts":report["counts"],
                "relationship_count":report["relationship_count"],"marker":report["marker"],
                "representatives":[{"name":row["name"],"shipment_id":row["shipment_id"],"custody_events":len(row["custody"]),
                    "expected":row["expected"],"lifecycle":row["lifecycle"],"codes":row["initial_supported_codes"]}
                    for row in report["representatives"]]}))


if __name__=="__main__":main()
