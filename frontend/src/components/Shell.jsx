import { Link } from "react-router-dom";

/*
  The frame for the two tools.

  Quiet on purpose. The landing is a public notice; from here on the product
  is a document, and the chrome should get out of the way of the clause.

  The step indicator is not decoration. Someone who has pasted a rejection
  letter and is being asked for a policy needs to know how much further this
  goes before they commit more effort — the research finding is that effort
  is the blocker, so the cost has to be visible and small.
*/
export default function Shell({ steps, current, foot, children }) {
  return (
    <div className="flex min-h-screen flex-col bg-paper">
      <header className="no-print border-b border-rule bg-paper">
        <div className="mx-auto max-w-6xl px-5 sm:px-8">
          <div className="flex items-baseline justify-between py-4">
            <Link
              to="/"
              className="font-doc text-body font-semibold tracking-tight text-ink hover:underline"
            >
              Claim Decoder
            </Link>
            <Link to="/" className="folio text-ink-soft hover:text-ink">
              Start over
            </Link>
          </div>

          {steps && (
            <ol className="flex flex-wrap gap-x-5 gap-y-1 pb-3">
              {steps.map((s, i) => {
                const state =
                  i < current ? "done" : i === current ? "now" : "todo";
                return (
                  <li
                    key={s}
                    aria-current={state === "now" ? "step" : undefined}
                    className={
                      "folio " +
                      (state === "now"
                        ? "text-ink"
                        : state === "done"
                          ? "text-ink-soft"
                          : "text-rule")
                    }
                  >
                    <span aria-hidden="true">
                      {state === "done" ? "●" : state === "now" ? "▸" : "○"}
                    </span>{" "}
                    {s}
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-8 sm:px-8 sm:py-12">
        {children}
      </main>

      <footer className="no-print border-t border-rule">
        <div className="mx-auto max-w-6xl px-5 py-8 font-doc text-aside text-ink-soft sm:px-8">
          {foot}
        </div>
      </footer>
    </div>
  );
}
