# Manifesto

> **TL;DR** `cptr` runs on your machine and serves your whole computer (files, terminal, editor, git) to any browser. Phone, tablet, laptop, another computer, even the one it's running on. Designed to feel native on every screen. Plug in an AI that can actually read, write, and run things on your machine, or bring your favourite terminal agent. Terminal multiplexer, parallel AI agents, full workstation, one tool, any device.

A developer moves to Portugal for the light. She works remotely for a company in New York. The commute is gone. The office is gone. Her apartment has a terrace with bougainvillea and a view of the Tagus. She sits at a desk in a dark room for eight hours and sees the river between pull requests.

A father works from home. His daughter is three. He is present in the house for every hour she is awake. He is available for almost none of them. "Working from home" means a closed door, a lit screen, and a posture that says: not now. She learns early that he is home but not here. Remote work promised presence. It delivered proximity.

A freelancer flies to Bali. The laptop comes out at a beach bar. The glare makes the screen unreadable. She moves to the shade, then to a cafe, then to an air-conditioned room with the curtains drawn. The beach was the point. The room is where the work happens. Every time.

These are not failures of discipline. These are consequences of design. The tools dictate the posture. The posture dictates the location. The location dictates what the life looks like. To understand why, it helps to understand how the desk became the default in the first place.

## The inheritance

Nobody chose the desk. It was inherited.

The first computers filled rooms. To use one, you went to it. When computers became personal, they became furniture. The PC sat on a desk because it weighed thirty pounds, drew power from a wall outlet, and connected to peripherals by cable. The desk was a physical requirement. Then laptops arrived, and the requirement became optional, but the habit did not change. The laptop was carried to a new desk. The coffee shop desk, the kitchen desk, the coworking desk. The posture remained. The human goes to the computer, opens it, sits down, begins.

The phone freed everything else. Communication, commerce, entertainment, education, banking, navigation. Every domain of modern life moved into the pocket. But development stayed at the desk, and for a long time, this was justified.

Writing code was typing-intensive work. It required rapid navigation across files, simultaneous visibility of multiple contexts, and sustained keyboard input. A six-inch screen and a touch keyboard were genuinely insufficient. The phone could not do the work because the work was production, and production demanded the apparatus: the large screen, the mechanical keyboard, the multiple panes, the fixed posture. The desk was not arbitrary. It was earned.

But the nature of the work is no longer the same.

## The shift

Software development has been, for its entire history, a high-input activity. Thousands of keystrokes to produce a single feature. Hundreds of lines written by hand, character by character, requiring constant visual scanning across multiple files. The ratio of human effort to machine output was enormous. Every feature was assembled manually from syntax and logic, and the speed of production was limited by the speed of the human's hands on a keyboard.

Artificial intelligence has inverted this ratio. A developer can now describe intent in a sentence and receive hundreds of lines of working code in return. The bottleneck has moved from production speed to judgment quality. The question is no longer "how fast can you type" but "can you evaluate what came back." The input bandwidth required from the human has dropped by orders of magnitude. The cognitive demand has not decreased. It has changed in kind.

This is a structural transformation in how software is made. The development loop itself has become asynchronous. A developer describes what they need. The AI produces it. The developer returns to review the result. This is unlike the old model, where every line required the developer's fingers on the keyboard in real time. In the new model, the developer does not need to be seated while the work is being produced. They need to be available when it is time to evaluate. That is a notification, not a posture.

The most valuable developer skill is shifting from the ability to produce code quickly to the ability to evaluate code accurately and articulate intent clearly. These are thinking skills. They benefit from movement, from stepping away, from a change of environment, from a clear head. The desk was optimized for typing speed. The new work is optimized for clarity of thought.

This is not speculative. It is measurable. Companies are restructuring engineering teams around AI-assisted workflows. The percentage of AI-generated code in production codebases is tracked and growing. GitHub reports that Copilot generates nearly half of all code in files where it is enabled. Entire startups are built with engineering teams a fraction of the size that would have been required five years ago. The trend is not ambiguous.

And the trend only moves in one direction. Every improvement in AI reduces the amount of manual input required from the developer. Every new model that writes better code, understands larger codebases, and makes fewer mistakes shifts the human role further from production toward judgment. The phone is sufficient for much of the work today. It will be sufficient for more of it tomorrow. This is not a bet against the current state of AI. It is a bet on the momentum of AI. The better AI gets, the less reason there is to be tethered to a desk.

## The computer, not the chat

But AI alone is not enough. AI does not replace the computer. It runs on the computer.

The AI writes code, but the code lands in a filesystem. The filesystem has structure, history, and dependencies. The code must be built, and the build produces output. The output must be tested, and the tests produce results. The results must be deployed, and the deployment produces logs. At every stage, the ground truth is on the machine. A chat interface shows what the AI generated. The computer shows what actually happened.

Evaluating AI-generated code is not reading a chat log. It is reviewing a diff in the context of the files around it. It is checking whether the tests pass. It is looking at the terminal output. It is seeing the git history. It is navigating the filesystem to understand what changed and why. The AI is a collaborator. The computer is the workspace. Judgment requires access to the workspace, not just the collaborator.

This is why the answer is not a better chat app on the phone. The answer is the phone reaching the computer itself. The whole computer. Files, terminal, editor, git, and yes, AI too, as part of the environment it already runs in. Not a feature list. Just the machine, accessible from the pocket.

## The choice

This is not an argument against the desk. Deep focus work benefits from a large screen, multiple panes of context, sustained uninterrupted attention. The desk is excellent for that, and nothing here suggests otherwise.

The argument is against the desk being mandatory.

Right now, every interaction with the computer requires the desk. Checking a build, reviewing a diff, approving a commit, reading a log, pushing a fix. All of it requires sitting down at the machine. The desk is currently the only way to reach your own computer. The question is not whether the desk is useful. It is whether it should be the only option.

Reviewing a complex change across twenty files on a phone sounds impractical. But it sounds impractical because it has been impractical, and it has been impractical because no one has built a good interface for it. Every mobile development tool to date has been a desktop interface compressed into a smaller screen. That is not a test of whether the phone can do the work. It is a test of whether a desktop layout survives being shrunk. It never does. The conclusion that phones are insufficient for serious code review is based entirely on experiences with interfaces that were not designed for the phone. It is the same conclusion people reached about mobile email before the iPhone, about mobile banking before good banking apps, about mobile photography before computational cameras. The screen was always capable. The interface was not.

## The cost of no choice

Over a forty-year career, at eight hours a day and two hundred fifty working days a year, a knowledge worker spends eighty thousand hours in a chair. That is more time than most people will spend with their children before those children leave home. More time than most couples will spend in the same room, awake, across an entire marriage. It is the largest single allocation of waking life that a modern knowledge worker will make.

Not all of those hours need to be at the desk. Some work demands deep focus, multiple contexts, sustained concentration. That work belongs at the desk. But a significant portion of the day is not deep focus. It is checking whether a build passed. It is reviewing a pull request. It is reading a log. It is approving a deploy. It is the connective tissue between the deep work. Right now, all of it requires the chair, because the chair is the only way to reach the machine.

The cost is not one thing. It is everything else. A parent behind a closed door for the hours the child is awake, including the hours that could have been flexible. A couple in the same house who see each other at the margins of the day. A person who moved somewhere beautiful and sees it through a window. The hours between nine and five are the hours when the sun is out, when the people you love are available, when the world is alive. Many of those hours go to the chair not because the work demands it, but because the tool does.

And the chair takes more than time.

## The body

The human body is not designed to be still. It is designed to move. The medical literature on this is not ambiguous.

A 2015 meta-analysis in the Annals of Internal Medicine, covering 47 studies, found that prolonged sedentary time is independently associated with increased risk of type 2 diabetes, cardiovascular disease, cancer, and all-cause mortality, even after adjusting for physical activity [1]. Sitting does damage that exercise does not fully undo. A 2016 meta-analysis in The Lancet, covering over one million people, found that those sitting eight or more hours per day needed 60 to 75 minutes of daily moderate-intensity physical activity to offset the elevated mortality risk [2]. Most people do not get 60 to 75 minutes. Recent research shows a roughly 3 percent increase in all-cause mortality risk for each additional hour of daily sedentary time, with those exceeding eleven hours per day facing 30 to 48 percent higher mortality compared to the least sedentary [3].

The developer who eats well, sleeps eight hours, and exercises before work will still spend the core of the day doing the one thing the research says not to do: sitting motionless for hours without interruption. Not because the work demands stillness. Because the interface does.

A healthier body also produces better work. A 2025 systematic umbrella review in the British Journal of Sports Medicine, synthesizing 133 prior systematic reviews, confirmed that exercise significantly improves general cognition, memory, and executive function across all age groups [4].

These are not incidental benefits. They are the exact cognitive capacities that the AI shift demands. The new work is evaluation, pattern recognition, architectural thinking, and the ability to articulate intent precisely. Every one of these improves with physical activity and degrades with prolonged stillness.

The desk was built for the old work. Movement is better suited to the new work. A 2014 study at Stanford, published in the Journal of Experimental Psychology, found that walking increased divergent thinking by up to 81 percent compared to sitting [5]. The effect was driven by the act of walking itself, not the environment. Divergent thinking is the capacity to generate multiple original ideas, to see a problem from new angles, to find solutions that are not obvious. It is, in practical terms, exactly what a developer directing AI needs to do well.

And yet the culture still says otherwise.

## The perception

"Serious work" looks like sitting at a desk. A developer reviewing code on a phone does not look like they are working. A developer hunched over a laptop in a dim room does. The posture has become the signal. Not the output, not the quality of thought, not the decisions made. The posture.

The belief that real work requires a desk is not based on evidence. It is based on the fact that everyone does it. Everyone does it because the tools require it. The tools require it because they were designed for the desk. This is a loop, not a reason. And it is a loop that others have already begun to break.

## The progress so far

The instinct to free the computer from the desk is not new. Others have acted on it, and each step has brought the work closer to where the developer actually is.

Cloud development environments moved the machine to a data center and accessed it through the browser. This solved the location problem but changed the ownership model: the machine is no longer yours. The environment, the uptime, the pricing belong to someone else. For many developers this tradeoff works well. But personal computing was built on a different promise, which was that the machine, the files, and the environment are yours.

Tools like code-server took a different approach. They kept the machine yours and served the development environment to your own browser. This honored ownership, and it was an important step. But the interface remained a desktop IDE: a wide viewport, a landscape screen, a keyboard, a mouse. It solved remote access. The next step is mobility.

The remaining distance is the interface. Not the protocol, not the architecture, not the ownership model. Those have been solved. What has not been solved is building an interface for the screen people actually carry. The technology to close that distance already exists.

## The pieces

The computer already has a network stack. It can serve applications over HTTP. The browser already knows how to render a full interface. The phone already has a screen and a persistent connection. Serve the computer to the phone. Files, terminal, editor, git. The real operating system, the real filesystem, the real shell. No emulation, no new infrastructure. Sessions persist across disconnects. The terminal does not die when the tab closes. Close the phone, walk away, come back on any device. The state is on the machine, where it belongs.

The interface must be built for the device people actually carry. Not a desktop IDE compressed into a mobile viewport. A tool designed from the ground up for the screen in the pocket. Touch-native. Portrait-native. Built for the way people actually hold their phone, not for the way they used to sit at their desk.

When that interface exists, the life changes.

## The life

Some people already work this way. They sit at the desk for the deep work because they choose to. They check a deploy from the park. They review a diff from the kitchen while dinner cooks. They push a fix from the train. They pick up their daughter from school and check the build from the bench at the playground while she climbs. When they need four panes and deep concentration, they go to the desk. When they do not, they do not. The computer is on their machine, reachable from their pocket, available at the desk when they want it and from anywhere else when they do not.

The tools shaped the posture. The posture shaped the location. The location shaped the life. Change the tool and the rest follows.

---

## References

[1] Biswas, A., et al. (2015). "Sedentary Time and Its Association With Risk for Disease Incidence, Mortality, and Hospitalization in Adults: A Systematic Review and Meta-analysis." *Annals of Internal Medicine*, 162(2), 123-132.

[2] Ekelund, U., et al. (2016). "Does physical activity attenuate, or even eliminate, the detrimental association of sitting time with mortality? A harmonised meta-analysis of data from more than 1 million men and women." *The Lancet*, 388(10051), 1302-1310.

[3] Patterson, R., et al. (2018). "Sedentary behaviour and risk of all-cause, cardiovascular and cancer mortality, and incident type 2 diabetes: a systematic review and dose response meta-analysis." *European Journal of Epidemiology*, 33(9), 811-829.

[4] Maher, C., et al. (2025). "Effectiveness of exercise for improving cognition, memory and executive function: a systematic umbrella review and meta-meta-analysis." *British Journal of Sports Medicine*.

[5] Oppezzo, M. & Schwartz, D.L. (2014). "Give Your Ideas Some Legs: The Positive Effect of Walking on Creative Thinking." *Journal of Experimental Psychology: Learning, Memory, and Cognition*, 40(4), 1142-1152.
