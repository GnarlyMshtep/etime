Here are some upgrades I want to make to etime. 

### Small tweaks to app flow
- Pause still does not consistently stop the pinging sound. The lifecycle should be updates so that paused never ping, even if they are overtime and haven't been stopped. Once the task is resumed it should continue pinging. (once u think u fixed it, lmk and I'll restart the app and check manually.)
- When we add a new task we should make sure that the etime menue is visible and that the new task is focused (has the arrow pointing to it). I often like to pause tasks as soon as I add them, so this makes this easier.
- I think etime continues working even when my Mac is on sleep (screen closed)? I want all task to pause if on sleep. (Is this easy?)
- it would be nice to have Ctrl + Opt + Cmd + h toggle up a little help menu which says what all the keys do? 
- add some metrics about the number of tasks ran in parallel during the day. 

### Small tweaks to dashboard UI 
- date picker in UI (remove the cmdline date picker option)

### Major change: 
- I want working time to be counted when it happens, not when task completes. This means we need to track every pause-unpause action inside the object (list of timestamps). Make this optional for backwards comptibility and revert to the old behavior? (is this clunky? we could edit the old data instead -- lets discuss this). 
- I want to also be able to add subtasks? I think maybe the simplest way to do this is 
    - add supertask field to task dataclass (just id / number in the list of the subtask )
    - add slight intend to view 
    - subtask can be selected as a toggle, and it subtasks the currently highlighted (arrow points to it), task in the view as the supertask
    - should be reflected in the web UI somehow (can be simple, no need for something complex)

### Stylistic changes 
- do lots of confetti when task is completed in "ambitious" but a little bit when completed otherwise. 
- can we try a different sound for the non-ambitious completion? finding it a bit boting. 


### Add these optional features which will not add for simplicty 
- editing tasks in the UI 
- chaning the corner of screen view is on. 