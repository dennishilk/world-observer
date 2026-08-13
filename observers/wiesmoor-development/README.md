# Wiesmoor City Development Observer

Checks the City of Wiesmoor's official `Auslegungen` directory and records the currently listed planning-document collections and their directly linked files. Document bodies are not downloaded or mirrored.

The observer uses deliberately conservative language. A directory entry means only that official documents were listed when the observer ran. It does not infer an open consultation, deadline, approval, construction stage, or other legal status. Dates are shown only when they are present in an official filename and are labelled as document dates rather than publication dates.

Run with `python observers/wiesmoor-development/observer.py`. Failure of an individual collection produces a partial snapshot; failure of the root official listing produces an `unavailable` snapshot.
