#!/usr/bin/env bash
set -euo pipefail
COMPOSE=${COMPOSE:-"docker compose"}
BASE_URL=${BASE_URL:-http://localhost:8000}
FAIL=0

pass() { echo "[PASS] $1"; }
fail() { echo "[FAIL] $1"; FAIL=1; }

echo "== smoke test =="

# 1. stack up (assume gia avviato o avviabile)
echo "1) stack"
$COMPOSE ps >/dev/null 2>&1 || true
$COMPOSE up -d --build >/dev/null
for i in $(seq 1 60); do
  code=$(curl -s -o /tmp/ready.json -w "%{http_code}" "$BASE_URL/ready" || true)
  if [ "$code" = "200" ]; then pass "stack up /ready 200"; break; fi
  sleep 2
  if [ "$i" = "60" ]; then fail "stack up /ready non pronto (ultimo $code)"; fi
done

# 2. login operator
echo "2) login"
TOKEN=$(curl -s -X POST "$BASE_URL/api/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=mbianchi&password=bootcamp" | python -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")
if [ -n "$TOKEN" ]; then pass "login operator"; else fail "login operator"; fi

# 3. advice 200 con citazioni o rifiuto coerente
echo "3) advice"
RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/ai/advice" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question":"Qual e il limite per un bonifico SEPA?"}')
CODE=$(echo "$RESP" | tail -n1); BODY=$(echo "$RESP" | sed '$d')
echo "$BODY" | python -c "import sys,json; d=json.load(sys.stdin); assert 'answer' in d" >/dev/null 2>&1 && [ "$CODE" = "200" ] \
  && pass "advice 200" || fail "advice 200 ($CODE)"

# 4. ACL: doc riservato non visibile a operator (best effort)
echo "4) ACL"
RESP2=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/ai/advice" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question":"Quali sono i limiti di esposizione risk only interni?"}')
CODE2=$(echo "$RESP2" | tail -n1); BODY2=$(echo "$RESP2" | sed '$d')
echo "$BODY2" | python - <<'PY' >/dev/null 2>&1 && pass "ACL (nessuna citazione risk_only)" || fail "ACL check"
import sys,json
d=json.load(sys.stdin)
cits=d.get('citations',[])
# non deve esporre documenti risk_only/compliance_only come fonti per operator
bad=[c for c in cits if 'risk' in (c.get('document_id','')+c.get('excerpt','')).lower() and 'limiti_esposizione' in c.get('document_id','')]
assert not bad
PY

# 5. cache hit: seconda chiamata identica, cerca cache_hit nei log api
echo "5) cache hit"
curl -s -X POST "$BASE_URL/api/ai/advice" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question":"Quanto costa un bonifico SEPA online?"}' >/dev/null || true
curl -s -X POST "$BASE_URL/api/ai/advice" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question":"Quanto costa un bonifico SEPA online?"}' >/dev/null || true
sleep 1
if $COMPOSE logs api --tail=200 2>/dev/null | grep -q 'cache_hit'; then pass "cache hit log"; else fail "cache hit log"; fi

# 6. DB giu -> /ready 503, API viva
echo "6) db giu"
$COMPOSE stop db >/dev/null
sleep 2
CODE6=$(curl -s -o /tmp/ready_db.json -w "%{http_code}" "$BASE_URL/ready" || true)
if [ "$CODE6" = "503" ]; then pass "db giu -> 503"; else fail "db giu -> 503 ($CODE6)"; fi
$COMPOSE start db >/dev/null

# 7. Redis giu -> cache degradata ma risposta comunque
echo "7) redis giu"
$COMPOSE stop cache >/dev/null
sleep 2
RESP7=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/ai/advice" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question":"Quanto costa un bonifico SEPA allo sportello?"}')
CODE7=$(echo "$RESP7" | tail -n1)
if [ "$CODE7" = "200" ] || [ "$CODE7" = "429" ]; then pass "redis giu -> risposta ($CODE7)"; else fail "redis giu ($CODE7)"; fi
$COMPOSE start cache >/dev/null

if [ "$FAIL" -ne 0 ]; then echo "SMOKE: FAILED"; exit 1; fi
echo "SMOKE: OK"
