# converter object
need a few specialised converters stored in a new utility class UtilConvert
# UTF-8 to a 8 bit character set with controlled loss
objective: implement a method converting a string in utf-8 to iso western latin (iso9959-2)
method name: utf8_to_iso8859_2(s:str) -> str
constraints: 
the majority of the input is covering usual names in europe (western including latin and eastern)
no need for kyrillic in eastern. 
the translation should make a best fit - at least looking good in english.
ideally I can edit the translation table in an externalized json table.¨
the translation should make sure any control characters lower than hex (20) are all translated to blank ' '

also make a test suite

