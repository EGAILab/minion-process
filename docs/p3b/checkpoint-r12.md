# CE-PROC-P3B-01 checkpoint proposal, revision 12 (base: contract revision 3 + checkpoint revisions 4–11)

**Author:** Claude `w1:p8`. **Status:** PROPOSED. Codex round 12 closed R003 at checkpoint level (K-42a′).
It kept K-43′'s lossless discovery order, the root-kind retention, the file-URL mapping and C-20d. R006
remains open on one dimension: the **resolution context** of locators that depend on context. This
revision replaces the drive-relative and rooted rows of K-43′'s table. It also adds a URL rule that the
author found while checking the table against real reference text. Revisions 4 to 11 otherwise stand,
and no closure is reopened.

## K-43″ context-dependent locators

- **Drive-relative (`X:name`) refuses.**
  - **Why:** a drive-relative locator resolves against that drive's current directory in the producer's
    context. A reference source has no declared producer context, so the broker cannot know that
    directory. Any leaf variant that contains a drive-relative candidate is context-dependent, and the
    cleanup is refused with the leaf named in the report. The broker never substitutes the drive root,
    a project root or any other directory as a guess.
  - **Recognition:** a drive-relative candidate is a single letter at a token start, followed by a colon
    and a name character other than a separator. Typical prose and YAML keys are words of two or more
    letters before the colon, so they do not match. A false match only refuses a cleanup, and the report
    names the leaf so that the Owner can correct it.
- **Rooted without a drive (`\name` or `/name` at a token start) is resolved on every drive.**
  - **Why this is exhaustive:** a rooted locator depends on context only through the *current drive*. It
    does not depend on any current directory: `\a\b` means `D:\a\b` for whichever drive `D` is current.
    The set of drive letters assigned on the host is finite and enumerable, so the broker resolves the
    candidate under **every** assigned drive letter, by K-43c.
  - **Outcome:** the cleanup is refused if any resolution reaches the copy. It is also refused if any
    drive's root or volume cannot be inspected, or if a drive resolves to a non-local final path.
    Proven-missing components under an inspected drive are lexical absence. Failed inspection is never
    lexical absence.
- **URLs are not locators.** A span that begins with `scheme:` followed by `//`, where the scheme is two
  or more letters and is not `file`, runs to the next whitespace or closing delimiter. Such a span is a
  URL, and no candidate is discovered inside it. Examples are an `https://` or `ssh://` link. Without this
  rule, every `https://host/...` link would contain a UNC-looking `//host/...` and refuse every cleanup.
  `file:` keeps K-43′'s mapping. A single letter before the colon is a drive, never a scheme.
- **Retained K-43′ cautions, stated as rules.**
  - An extended UNC form `\\?\UNC\host\share\...` keeps its UNC namespace when its inner root is
    derived. It is handled as UNC, never as a rooted path.
  - A failed root or volume inspection is kept distinct from proven-missing components, and only the
    latter is lexical absence.
- **The resulting partition is total.** Every candidate is exactly one of:
  - URL, which is excluded;
  - device or extended, which is reduced to its inner kind;
  - UNC, which is resolved and refused unless it is local;
  - drive-absolute, which is resolved;
  - rooted, which is resolved under every assigned drive;
  - drive-relative, which refuses.

  Name and label tokens (revision 9) still run on every variant.
- **Witnesses:**
  - **W-100g, generated:** resolution context {drive root, project root, nested current directory,
    another drive's stored current directory, unknown context} × root kind {drive-relative, rooted}. A
    drive-relative candidate refuses in every context. A rooted candidate reaches the copy through an
    alias on any one drive and refuses, and a drive that cannot be inspected refuses.
  - **W-100h, Codex's round-12 pair:** the leaf `Evidence retained at E:opaque-alias` refuses, with the
    contextual alias present and also with the alias pointing at an unrelated folder. Refusal of a
    context-dependent locator does not depend on the guessed folders. The positive cleanup path is
    covered by W-100e's sibling negatives for kinds that do not depend on context.
  - **W-100i, URL spans:**
    - `https://github.com/org/repo/issues/1`, `ssh://host/x` and `git+https://host/x` do not refuse;
    - `file://host/share/x` reaches UNC handling;
    - `x:1` at a token start refuses as drive-relative;
    - `key: value` and `Note: text` do not refuse.
  - **W-100j:** the extended UNC form `\\?\UNC\h\s\p` is handled as UNC.
- **Controls:**
  - **C-20e:** joining a drive-relative candidate only to the drive and project roots, which was
    revision 11's rule, authorizes W-100h.
  - **C-20f:** without the URL rule, every cleanup in W-61, the ordinary positive witness, is refused
    when an open work package contains an `https://` link. The control demonstrates over-refusal, so
    W-61's positive path must actually run.

## K-45 amended again

- **K-43 matrices** add resolution context × root kind (W-100g) and URL-span recognition (W-100i).
- **Controls** add C-20e and C-20f to the executed in-memory set.

## Request

Independent checkpoint review (§11.8.5) of revision 12's K-43″ and the amended K-45: **AGREED FOR
IMPLEMENTATION**, or REJECTED with the failing dimension and a counterexample.
