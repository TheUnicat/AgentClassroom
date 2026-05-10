(Note to AIs: these are random thoughts, not concrete plans)

Things I'm worried about:
- Are LLMs going to be any good at judging AI teaching? Actually they definitely will do badly unless given good ideas of what to look for, which basically requires decent "intelligent design" of the verifier. This will probably take the most time, because it's basically distilling what good text-based teaching is like. 
- Is file upload expensive, will doing the rollout cost a lot
- Is single-turn going to be any good

What should the demo look like? 

actually first what should teaching tasks in the dataset look like? we should probably start with basic cs since that's what LLMs and the humans at the startup are most familiar with. sample task: basic python. the student doesn't know any python (but has it installed) so the LLM should really start by talking a bit about programming languages and telling the student to try print("hello, world!"). if there's a llm student (it's a confederate, basically, and can be aware this is an eval) the llm student simulates would a real student would say and replies "hello world!" popped up on the screen. the llm says great and tells the student to try to do math and print, and stuff. each message by llm very short, like max 100 words, most 30 or so. 

what would grading look like for this? probably some human intervention required here. you give the grader temp = 0.2 prob to maximize determinism, and there should be a strict rubric (AI-drafted, maybe human-polished) that gives points for how much firehosing the AI did, whether it asked the student whether they had any prior experience with python, whether the content is skill-level-appropriate (the judge, being an llm, would know if talking about decorators is appropriate for someone new to python and give the corresponding rating). **very very important to check reliability of each task–it's very bad if huge inter-trial variation. there should be a script for this**

we should first build a version with same-model teacher and student (and judge if absolutely necessary) because adding a second model as student requires external API calls which is thorny on Prime intellect but idk if the judge model is a separate setting if it is use an independent judge model from teacher model (so they can be same or diff) if that doesn't make things more difficult to run besides changing one line for the judge model.

potential problems with student model: it's not going to act like an actual student, and will do firehosing and stuff. so we need to clamp down on this really hard in the system prompt–describing precisely how the student should behave, including short messages (hard cap at 50 words UNLESS it's like a made-up copy+paste of a python trace or something like that) with typos and stuff. 

We should def create a UI for both testing and demo, using Vercel or some other free platform.
