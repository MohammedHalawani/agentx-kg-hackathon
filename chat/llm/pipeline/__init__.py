"""GraphRAG complaint-resolution pipeline: classify -> recommend -> review, with an
adaptive feedback loop (AFL) that sends a rejected recommendation back to the classifier
instead of failing the whole run.

This is entirely separate from chat/llm/agent.py's two-tool ReAct chat agent and from the
governance domain (Mandate/Committee/Track/...) that the rest of chat/ and backend/ serve.
It runs against its own Neo4j database (config.SHIPMENT_DATABASE) loaded from the shipment
knowledge graph built in the sibling Saudi-Arabia-Regions-Cities-and-Districts project
(see shipment_kg/generate_shipment_kg.py there for how the data was generated, and
shipment_kg/shipment_dataset.dump for the graph itself). Reuses this app's existing
config.py (Neo4j creds, LLM_MODEL/EMBEDDING_MODEL via LiteLLM+Ollama) and the
core/query_runner.get_driver() connection - just pointed at a different database - so
nothing about Neo4j connection handling is duplicated.

Shipment graph shape (10 labels, all in config.SHIPMENT_DATABASE):
    (Order)-[:HAS_SHIPMENT]->(Shipment)
    (Order)-[:PLACED_BY]->(Customer)-[:LIVES_AT]->(Address)
    (Shipment)-[:DELIVERED_TO]->(Address)
    (Shipment)-[:ASSIGNED_TO]->(Courier)
    (Shipment)-[:GOVERNED_BY]->(Policy)
    (Shipment)-[:HAS_EVENT]->(Event)
    (Event)-[:CAUSED_BY]->(FailureReason)                       -- failed shipments only
    (FailureReason)-[:RESOLVES_WITH]->(Resolution)-[:HAD_OUTCOME]->(Outcome)
        -- only the ~150 already-resolved cases; ~70 "live" FailureReason nodes stop
        -- there with no Resolution yet - those are exactly the cases this pipeline
        -- is meant to process, using the resolved ones as retrievable precedent.

Pipeline stages (each is its own module here, none wired together yet - see graph.py):
    extract    -- free-text complaint -> structured query (city/district/courier/category/
                  shipment_id if known)
    retrieve   -- vector_search (KNN over FailureReason.case_summary embeddings) +
                  graph_traversal (N-hop from matched nodes) fused by reciprocal-rank-fusion
                  into one contextual subgraph
    classifier -- root-cause classification + confidence + priority over that subgraph
    recommender -- proposes an action, grounded in similar resolved cases
    reviewer   -- accepts or rejects the recommendation against SLA/evidence/rules/history;
                  a rejection feeds back into classifier (the AFL loop) rather than ending
                  the run
    writeback  -- on acceptance, appends the new (FailureReason)-[:RESOLVES_WITH]->
                  (Resolution)-[:HAD_OUTCOME]->(Outcome) chain, growing the retrievable
                  history for future runs

state.py defines the LangGraph state threaded through all of the above; graph.py will
compile them into the actual StateGraph once each stage has real logic.
"""
