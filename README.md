# Palace
A programming language of speaking and listening.

Design Goals:

1. The user can write any program entirely with their voice and ears.
2. The user can convey their program with short english utterances ("commands").
3. The IDE gives feedback about the validity of each command as it is given.
4. The user can query the IDE to understand the program in-progress.
5. Uses a Mind Palace metaphor whenever this does not conflict with goal 2.

Example session:

USER: new palace [called|named] fibbonacci
IDE: yes //commands work with or without superfluous words
USER: open [it|fibonacci]
IDE: yes //"it" is last item referenced.  If left blank, value is assumed to be "it"
USER: new room helper
IDE: yes // we could have added a wing in-between palace and room, but not neccesary
USER: new chain sequence
IDE: chain must be in a room
USER: enter helper
IDE: yes
USER: enter new tool adder
IDE: yes // we can create and enter in one command
USER: new chain sequence
IDE: yes
USER: add new link to sequence
IDE: link 1 added
USER: set link one value [to] zero 
IDE: yes //the type of the chain is now set implicitly
USER: add new link to sequence
IDE: link 2 added
USER: set link value to one
IDE: yes //though link is not named, we know it's link 2
USER: where am I?
IDE: tool adder, room helper, palace fibonacci
USER: What is the value of link 2?
IDE: one
USER: add link to input called place
IDE: yes //all tools have a chain called input of type "box" which can hold anything.  It's essentially the parent variable type.
USER: set step one to 

