# Domande di valutazione — Giorno 5

Undici domande a cui i documenti rispondono, una per ciascuna informazione che so dove sta, più
cinque plausibili ma non coperte. Il documento atteso è indicato per le positive; per le negative
la risposta attesa è il rifiuto.

| id | domanda | risposta nei documenti? | documento atteso |
|----|---------|--------------------------|------------------|
| q01 | Qual è il limite massimo di un bonifico extra-SEPA disposto online? | sì | circolare_limiti_estero |
| q02 | Oltre quale importo un bonifico extra-SEPA richiede l'autorizzazione dell'Area Estero? | sì | circolare_limiti_estero |
| q03 | Qual è il codice della procedura per i bonifici esteri sospesi? | sì | circolare_limiti_estero |
| q04 | Qual è il codice della procedura per le segnalazioni di operazioni sospette? | sì | circolare_segnalazioni |
| q05 | Qual è il codice del programma per i clienti storici? | sì | circolare_clienti_storici |
| q06 | Qual è il canone annuo della carta oro per un cliente storico? | sì | circolare_clienti_storici |
| q07 | Entro quante ore va valutata una segnalazione di operazione sospetta? | sì | circolare_segnalazioni |
| q08 | Qual è la soglia per le operazioni in contanti che richiedono identificazione e causale? | sì | circolare_segnalazioni |
| q09 | Quanto costa un bonifico istantaneo SEPA online? | sì | commissioni_bonifico |
| q10 | Qual è il plafond mensile della carta di credito oro? | sì | condizioni_carta_credito |
| q11 | Qual è il canone mensile del conto corrente principale? | sì | regolamento_conti |
| q12 | Qual è il tasso del mutuo agevolato per giovani coppie? | no | — |
| q13 | Qual è il rendimento del conto deposito vincolato a 12 mesi? | no | — |
| q14 | Che commissione si applica al trading online di azioni? | no | — |
| q15 | Qual è il limite del fido di cassa per le piccole imprese? | no | — |
| q16 | Quali documenti servono per aprire un conto titoli? | no | — |

Il file leggibile dal codice è `domande_g5.jsonl`, con gli stessi campi più `gold_phrase` per la
misura a livello di passaggio.

## Domande su importi e codici

Un secondo insieme, `domande_g5_esatte.jsonl`, mette alla prova il recupero esatto: dieci codici e
dieci importi. Sono le domande in cui il vettore da solo può perdere il passaggio giusto anche
quando il documento è quello giusto, ed è lì che la ricerca lessicale deve dare una mano.

| id | domanda | documento atteso |
|----|---------|------------------|
| p01 | PRCEST07 | circolare_limiti_estero |
| p02 | MODEST50 | circolare_limiti_estero |
| p03 | Lista GRUPPO-A | circolare_limiti_estero |
| p04 | CIRS10 | circolare_clienti_storici |
| p05 | PRCAGEV10 | circolare_clienti_storici |
| p06 | PRCSEGN14 | circolare_segnalazioni |
| p07 | MODSEGN14 | circolare_segnalazioni |
| p08 | A cosa serve la MODEST50? | circolare_limiti_estero |
| p09 | A cosa serve la PRCAGEV10? | circolare_clienti_storici |
| p10 | Dove trovo la Lista GRUPPO-A? | circolare_limiti_estero |
| n01 | 15.000 EUR | circolare_limiti_estero |
| n02 | 50.000 EUR | circolare_limiti_estero |
| n03 | 100.000 EUR | circolare_limiti_estero |
| n04 | 30 EUR | circolare_clienti_storici |
| n05 | €5.000 | condizioni_carta_credito |
| n06 | €4.00 | regolamento_conti |
| n07 | €1.00 | commissioni_bonifico |
| n08 | 24 ore | circolare_segnalazioni |
| n09 | 10.000 EUR | circolare_segnalazioni |
| n10 | 0,20% | circolare_limiti_estero |
