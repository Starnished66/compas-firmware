# Provenance and licence

libssc is the Compás project's own reverse-engineered implementation of the Samsung Scalable Codec
(SSC) encoder, written for interoperability so that Compás players can stream SSC to compatible
Bluetooth earbuds. It was started by the Compás project together with Gemini and Astra (AI coding
assistants) by analysing the behaviour and data of an encoder binary and then translating and
verifying the result in C against that binary's output.

It contains no code licensed from Samsung, and Samsung has granted no licence for it. The project
makes no claim of endorsement by or affiliation with Samsung. Coefficient tables in
`ssc_image_data.h` are data needed for bit-exact interoperability.

Licence: GNU General Public License v3.0, the same as the rest of this repository
(see `LICENSE`). Copyright (c) the Compás project contributors.
