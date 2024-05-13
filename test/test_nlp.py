from unittest.mock import patch

import spacy

from src.nlp import find_locations


def blank_pipeline_with_place_patterns():
    nlp = spacy.blank('en')
    ruler = nlp.add_pipe('entity_ruler')
    ruler.add_patterns(
        [
            {'label': 'GPE', 'pattern': 'Spain'},
            {'label': 'GPE', 'pattern': 'UK'},
            {'label': 'LOC', 'pattern': [{'LOWER': 'lake'}, {'LOWER': 'como'}]},
            {'label': 'PERSON', 'pattern': 'Ada'},
        ]
    )
    return nlp


def test_find_locations_with_a_real_spacy_pipeline():
    nlp = blank_pipeline_with_place_patterns()
    with patch('src.nlp.get_nlp', return_value=nlp):
        locations = find_locations(text='Ada says Spain is sunnier than the UK, and Spain beats Lake Como')
    assert locations == ['Spain', 'UK', 'Lake Como']
