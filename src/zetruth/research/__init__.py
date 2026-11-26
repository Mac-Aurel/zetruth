"""Recherche d'une affirmation par un modèle de langage, limitée à la liste blanche.

Le modèle cherche et lit les pages officielles, puis propose un verdict avec
des extraits. Le code décide de ce qui est retenu (zetruth.research.checks) :
un extrait qui ne figure pas mot pour mot dans une page officielle lue pendant
la recherche est écarté, et une comparaison de chiffres est refaite en code.
"""
