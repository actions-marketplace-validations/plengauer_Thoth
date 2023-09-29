import sys
import os
import json
import requests
import opentelemetry
from opentelemetry.sdk.resources import Resource, ResourceDetector, OTELResourceDetector, get_aggregated_resources
from opentelemetry.sdk.trace import TracerProvider, sampling
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry_resourcedetector_docker import DockerResourceDetector
from opentelemetry_resourcedetector_kubernetes import KubernetesResourceDetector
from opentelemetry.trace import SpanKind
from opentelemetry.sdk.trace import Span, StatusCode
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

class AwsEC2ResourceDetector(ResourceDetector):
    def detect(self) -> Resource:
        try:
            token = requests.put('http://169.254.169.254/latest/api/token', headers={ 'X-aws-ec2-metadata-token-ttl-seconds': '60' }, timeout=5).text
            identity = requests.get('http://169.254.169.254/latest/dynamic/instance-identity/document', headers={ 'X-aws-ec2-metadata-token': token }, timeout=5).json()
            hostname = requests.get('http://169.254.169.254/latest/meta-data/hostname', headers={ 'X-aws-ec2-metadata-token': token }, timeout=5).text
            return Resource.create({
                'cloud.provider': 'aws',
                'cloud.platform': 'aws_ec2',
                'cloud.account.id': identity['accountId'],
                'cloud.region': identity['region'],
                'cloud.availability_zone': identity['availabilityZone'],
                'host.id': identity['instanceId'],
                'host.type': identity['instanceType'],
                'host.name': hostname
            })
        except:
            return Resource.create({})

resource = {}
spans = {}

def main():
    fifo_path = sys.argv[1]
    scope = sys.argv[2]
    version = sys.argv[3]
    while True:
        with open(fifo_path, 'r') as fifo:
            for line in fifo:
                line = line.strip()
                if len(line) == 0:
                    continue
                tokens = line.split(' ', 1)
                tokens = [token for token in tokens if token]
                try:
                    handle(scope, version, tokens[0], tokens[1] if len(tokens) > 1 else None)
                except EOFError:
                    sys.exit(0)
                except Exception as error:
                    print(error)

def handle(scope, version, command, arguments):
    match command:
        case 'RESOURCE_ATTRIBUTE':
            key = arguments.split('=', 1)[0]
            value = arguments.split('=', 1)[1]
            resource[key] = value
        case 'INIT':
            tracer_provider = TracerProvider(sampler=sampling.ALWAYS_ON, resource=get_aggregated_resources([
                    AwsEC2ResourceDetector(),
                    KubernetesResourceDetector(),
                    DockerResourceDetector(),
                    OTELResourceDetector(),
                ]).merge(Resource.create(resource)))
            tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter() if os.environ.get('OTEL_TRACES_CONSOLE_EXPORTER') == 'TRUE' else OTLPSpanExporter()))
            opentelemetry.trace.set_tracer_provider(tracer_provider)
        case 'SHUTDOWN':
            opentelemetry.trace.get_tracer_provider().force_flush()
            raise EOFError()
        case 'SPAN_START':
            tokens = arguments.split(' ', 3)
            response_path = tokens[0]
            trace_parent = tokens[1]
            kind = tokens[2]
            name = tokens[3]
            span = opentelemetry.trace.get_tracer(scope, version).start_span(name, kind=SpanKind[kind.upper()], context=TraceContextTextMapPropagator().extract({'traceparent': trace_parent}))
            spans[str(span.context.span_id)] = span
            with open(response_path, 'w') as response:
                response.write(str(span.context.span_id))
        case 'SPAN_END':
            span_id = arguments
            span : Span = spans[span_id]
            span.end()
            del spans[span_id]
        case 'SPAN_ERROR':
            span : Span = spans[arguments]
            span.set_status(StatusCode.ERROR)
        case 'SPAN_ATTRIBUTE':
            tokens = arguments.split(' ', 1)
            span_id = tokens[0]
            keyvaluepair = tokens[1]
            tokens = keyvaluepair.split('=', 1)
            key = tokens[0]
            value = tokens[1]
            span : Span = spans[span_id]
            span.set_attribute(key, value)
        case 'SPAN_TRACEPARENT':
            tokens = arguments.split(' ', 1)
            response_path = tokens[0]
            span_id = tokens[1]
            span : Span = spans[span_id]
            carrier = {}
            TraceContextTextMapPropagator().inject(carrier, opentelemetry.trace.set_span_in_context(span, None))
            with open(response_path, 'w') as response:
                response.write(carrier.get('traceparent', ''))
        case '_':
            return

if __name__ == "__main__":
    main()
