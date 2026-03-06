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
USER: enter it
IDE: yes //"it" is last item referenced (in the utterance, not in the syntax tree!).  If left blank, value is assumed to be "it"
USER: new room helper
IDE: yes // we could have added a new wing in-between palace and room, but it's not neccesary
USER: new chain sequence
IDE: chain must be in a room
USER: enter helper
IDE: yes
USER: enter new device adder
IDE: yes // we can create and enter in one command
USER: new chain sequence
IDE: yes
USER: append new link to sequence
IDE: link 1 added
USER: set link 1 value [to] 0 
IDE: yes //the type of the chain is now set implicitly
USER: append new link to sequence
IDE: link 2 added
USER: set link value to 1
IDE: yes //though link is not named, we know it's link 2
USER: append 1 to sequence
IDE: yes // shortcut for "append link to sequence.  set it's value to 1."
USER: [what is the] length of sequence?
IDE: 3
USER: where am I?
IDE: tool adder, room helper, palace fibonacci
USER: What is the value of link 2?
IDE: 1
USER: What is link 1?
IDE: link 1 is a link with name "link 1" and value 0 and next link "link 2"
USER: append link to input called place
IDE: yes //all devices have a chain called input of type "box" which can hold anything.  It's essentially the parent variable type.
USER: set step 1 to new if
IDE: yes // "step" should be syntax sugar for accessing the links in a chain of type "command".  There is only 1 chain of type "command" in a device, which is its "process"
USER: 
