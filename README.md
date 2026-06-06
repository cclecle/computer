# cptr

![Cptr Demo](./demo.png)

The computer used to be a room. Then a desk. Then a bag. Now it's a URL.

Your phone goes everywhere with you. You run your life from it. Your computer used to stay home. Now it can come along.

`cptr` (short for "computer") runs on your machine and puts the whole thing in a browser tab. Pull out your phone and you're in. Files, editor, terminal, git, running on the computer you already own.

Push a hotfix from the train. Check on a deploy from bed. Ship a side project from the park. Stage and commit without touching the command line, or open the terminal and do it the old way. Search across files. Preview markdown. Drag things around. Switch between projects without losing your place.

Close the tab. Come back tomorrow on any device. Everything is where you left it. Sessions survive disconnects. Your work doesn't care which screen you're on.

AI is there if you want it. Bring your own key. Works fine without it.

Life is short. Touch grass.

## Design principles

**Mobile is first-class.** The interface is built for the phone. Touch-native, portrait-native, designed for the screen people carry. Sessions survive disconnects because on a phone, they will. If a feature only works at a desk, it's not done.

**Your machine.** cptr serves the machine it runs on. The local filesystem, the local shell, local state. Where that machine lives is up to you.

**Computer, not chat.** The core is the filesystem, the terminal, and git. Files over apps. Plain files on your machine, not content trapped inside another product. AI conversations are files too: searchable, editable, movable, commit-able. cptr is a window into the real system, not a container on top of it.

Read our [Manifesto](MANIFESTO.md).

## Install

```bash
pip install cptr
```

## Run

```bash
cptr run
```

Opens in your browser. From other devices:

```bash
cptr run --host 0.0.0.0
```

## License

Open Use License. Source available. All rights reserved. See [LICENSE](LICENSE). [Enterprise licenses available](mailto:sales@openwebui.com).
