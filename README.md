# Palace
A programming language of speaking and listening.

Design Goals:

1. The user can write any program entirely with their voice and ears.
2. The user can convey their program with short english utterances ("commands").
3. The IDE gives feedback about the validity of each command as it is given.
4. The user can query the IDE to understand the program in-progress.
5. Uses a Mind Palace metaphor whenever this does not conflict with goal 2.

Example session below.  Parts in brackets are optional for the user input.  Parts in brackets separated by a pipe character show two separate posibilities for an optional section of user input.

USER: palace [called|named] fibbonacci //type names double as instantiation function name
IDE: yes //commands work with or without superfluous words
USER: enter it
IDE: yes //"it" is last item referenced (in the utterance, not in the syntax tree!).  If left blank, value is assumed to be "it"
USER: room helper //just for example
IDE: yes // we could have added a new wing in-between palace and room, but it's not neccesary
USER: chain sequence //"sequence" is a string, but the instantiation command knows that that argument takes a string and makes it the name
IDE: chain must be in a room
USER: enter lobby
IDE: yes // every palace starts with a room named "lobby"
USER: chain sequence over // if you don't want to wait for the silent period you can say "over" to end a line
IDE: yes
USER: append link to sequence
IDE: yes
USER: set link value [to] 0
IDE: yes //the type of the chain is now set implicitly, but you can also set it explicitly
USER: set sequence['s] link 2 to 1 //closer to array-style syntax also accepted.  <chain name> <index> is <value>
IDE: yes //if they had said 'sequence 8 is 5' then a bunch of empty links would have been added in-between
USER: set link value to 1
IDE: yes 
USER: append 1 to sequence // shortcut for "append link to sequence.  set it's value to 1."
IDE: yes //though link is not named, we know it's link 3 (for now -- links can also be inserted)
USER: append false to sequence
IDE: cannot append boolean to chain of type number //error messages try to explain what's wrong with the user input
USER: [what is the] length of sequence?
IDE: 3
USER: enter new device adder over //device is equivalent to function
IDE: yes // we can create and enter in one command
USER: set comment to this is a device for calculating fibbonacci numbers recursively //a device is basically a function with a single input variable and a chain of commands called "process" and a "run" command associated with it
IDE: noted //every object has a blank 'comment' section with a string that can be queried in the IDE but is removed at compile time
USER: where am I?
IDE: device adder, room helper, palace fibonacci
USER: what is the value of sequence link 2? //could also be said as "what is sequence link 1's value?"
IDE: 1
USER: what is sequence link 1?
IDE: link 1 is a link with value 0 and next link "link 2" // it has no name now, but anything can be named
USER: set input name to place stop  // if you are specifying a string that ends before the end of the line, you have to add "stop" to tell it to end the string. You can also use it at the end of a line if you want
IDE: yes //all devices have a box (untyped variable) called "input".  There's only one, so if you need multiple arguments you have to put them in a data structure.
USER: set input type to integer
IDE: yes
USER: enter process //There is a chain of type "command" in a device, which is called a "process" (that is the name of the subtype).  The name of the process by default is "step".
IDE: yes
USER: set step 1 to if place [is] less than length of sequence
IDE: yes // 
USER: set step 2 to return sequence link input
IDE: yes
USER: what is step length?
IDE: 2
USER: set step 3 to else
IDE: yes
USER: then set new box a to sequence link input minus 2 //"then" is syntax sugar for "append link with value..."
IDE: yes
USER: then set new box b to sequence link input minus 1
IDE: yes
USER then sequence link input is a plus b
IDE: yes
USER: then return sequence input
IDE: yes
USER: run adder
IDE: adder requires an input of type integer
USER: run adder on 5 //it's OK that we're inside the device
IDE: 3
USER: exit
IDE: yes
USER: run adder on 8
IDE: 13
USER: go to helper //you can run straght to another room
IDE: yes
USER: run adder on 9
IDE: no device adder
USER: run lobby's adder on 9
IDE: 21
USER: go outside //"outside" is a special null room outside the palace
IDE: yes
USER: run fibonacci's lobby's adder on 10
IDE: 34
