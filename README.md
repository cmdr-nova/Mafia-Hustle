# Mafia-Hustle

This is an **incomplete** Mafia Wars clone, stripped down to its absolute basics. It uses python, bcrypt, sqlalchemy, and flask. The *reason* it's not complete, is because, halfway through formulating what I wanted to do, I realized, even with an encrypted database storing usernames and passwords, I could *still* be liable for a breach and I just don't think I want that responsibility. At least ... not right now.

The code has errors in it, some stuff is there that probably shouldn't be. This is mostly hacked together through things I've been learning, and lots of Google searches. 

Absolutely fork this if you feel up to the task, but I'm putting it here as a, "Hey, I was gonna do this, but I decided definitively, **not to**."

(the database probably needs to be remade, because I scrubbed my own info out of it)

Features:

- uers can attack other users on the leaderboard to gain points to level up and gain kills
- users can lose health randomly from either being attacked, or while attacking others
- users can die, where the only function is to heal via finding food (at random)
- users can run random jobs for money
- max level is 60
- prestige levels are theoretically infinite
- users can upload their own avatar to represent themselves

Planned, not implemented:

- users should be able to buy weapons
- users should have a home base where they can't be attacked
- the game should show your avatar to other players
- an "active player" database with search function


