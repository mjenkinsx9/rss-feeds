# Content policy

This project turns publicly readable web pages into RSS feeds. To keep it
something we're comfortable hosting and publishing, requested feeds are reviewed
against this policy — first automatically by a bot, then by a human before any
pull request is merged.

## What we won't build a feed for

A request is **declined** if the source site is primarily any of the following:

- **Pornographic / adult** — sexual or adult content.
- **Violence / gore** — graphic violence, gore, or content glorifying violence.
- **Gambling** — betting, casinos, or gambling promotion.
- **Hate, extremist, or otherwise harmful** — hate speech, extremist or
  terrorist content; and the adjacent "too extreme" bucket: illegal goods or
  services, malware distribution, scams/fraud, and targeted harassment or
  doxxing.

Borderline or genuinely ambiguous cases are declined by default — the reviewer
errs on the side of not building the feed. A page that mixes a small amount of
the above into otherwise ordinary content is judged on what it is *primarily*
about.

We also can't build a feed for a page that isn't feed-shaped — there has to be a
repeating list of entries (posts, releases, changelog items, …) for selectors to
target. Pages that render their entire list with client-side JavaScript usually
return nothing to a plain fetch and can't be supported by this engine.

## How review works

1. You open a [feed request issue](../../issues/new?template=request-feed.yml).
2. A GitHub Action sends the request and the page to Claude, which moderates it
   against this policy and — if it passes — proposes the CSS selectors.
3. If it passes, the bot opens a pull request adding the feed to `feeds.yaml`
   and links it to your issue. A maintainer reviews and merges.
4. If it's declined, the bot comments with the reason and closes the issue.

This policy is applied on a best-effort basis and the maintainers' decision is
final. Being listed here is not an endorsement of any site; see the disclaimer
in the [README](./README.md).
