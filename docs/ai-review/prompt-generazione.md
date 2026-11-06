# Review del prompt di generazione delle circolari

## Prompt ricevuto

> Scrivimi tre circolari interne verosimili di una banca italiana, di circa una pagina ciascuna, su
> limiti dei bonifici verso l'estero, condizioni agevolate per i clienti storici e obblighi di
> segnalazione. Italiano burocratico credibile, con importi e soglie precise. Solo i tre testi.

## Dove il modello si sente autorizzato a completare

1. **«verosimili»** autorizza a inventare ciò che rende credibile il testo: nomi di procedure,
   moduli, liste di paesi, organi interni. Nessuna di queste invenzioni è distinguibile da un dato
   reale una volta che finisce nel corpus.
2. **«importi e soglie precise»** senza una fonte spinge a produrre numeri tondi ma arbitrari
   (15.000, 50.000, 24 ore, 10 anni). La precisione richiesta viene scambiata per accuratezza.
3. **«italiano burocratico credibile»** premia il registro, non la verificabilità: una frase che
   suona come una circolare vera passa anche se il contenuto è inventato.
4. **«circa una pagina»** fissa la lunghezza, non i confini del contenuto: per riempire la pagina il
   modello aggiunge dettagli che non gli sono stati chiesti (sanzioni, responsabilità, allegati).
5. **Nessun vincolo su ciò che non si sa**: il prompt non dice «se un dato non è fornito, non
   inventarlo». Il default del modello è completare, non dichiarare l'ignoranza.
6. **Nessun riferimento a un corpus di partenza**: il modello non ha un contesto da cui estrarre,
   quindi l'unica fonte disponibile è la propria conoscenza generale del settore bancario.

## Conseguenza per il RAG

Le tre circolari generate sono state accettate come documenti interni di prova. Questo è lecito
perché il corpus è dichiaratamente finto e serve a misurare il recupero, non a rispondere a
clienti. Se lo stesso prompt fosse usato per produrre documenti veri, il rischio sarebbe quello
della commessa: una condizione inventata, scritta in italiano perfetto, indistinguibile da una
circolare reale.
