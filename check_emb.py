from neo4j import GraphDatabase
d = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'semantic-layer-password'))
with d.session() as s:
    for r in s.run('MATCH (t:Table) WHERE t.embedding IS NOT NULL RETURN \"Tables\" AS type, count(t) AS count UNION ALL MATCH (k:KPI) WHERE k.embedding IS NOT NULL RETURN \"KPIs\" AS type, count(k) AS count UNION ALL MATCH (b:BusinessConcept) WHERE b.embedding IS NOT NULL RETURN \"Concepts\" AS type, count(b) AS count UNION ALL MATCH (e:QueryExample) WHERE e.embedding IS NOT NULL RETURN \"Examples\" AS type, count(e) AS count'):
        print(f"{r['type']}: {r['count']} with embeddings")
d.close()
